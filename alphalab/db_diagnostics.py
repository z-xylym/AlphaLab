"""Read-only connection diagnosis. Never expose exception text or connection values."""
import errno
import queue
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ADVICE = {
    'CONFIGURATION_ERROR': '在GitHub Secrets核对SQLAlchemy URL前缀、密码URL编码及Connect面板的Session pooler配置；不需要先重置密码。',
    'POOLER_CONFIGURATION_ERROR': '使用Supabase Connect面板的Session pooler、端口5432及含项目标识的用户名；不要混用transaction pooler或直连配置。',
    'DNS_ERROR': '核对Connect面板的pooler主机是否复制完整；检查DNS服务或稍后重试，不要更换密码。',
    'NETWORK_ERROR': '核对5432端口、项目是否暂停、Supabase数据库网络限制及GitHub runner出站网络；不要关闭全部网络限制。',
    'AUTHENTICATION_ERROR': '核对Session pooler用户名中的项目标识和Secret中的密码URL编码；认证失败不等于必须重置密码。',
    'DATABASE_NOT_FOUND': '在Connect面板核对数据库名；不要新建或删除数据库来试错。',
    'TLS_CERTIFICATE_ERROR': '保留sslmode=verify-full；核对pooler主机名与证书，并使用Supabase官方根CA修复信任链。',
    'TLS_CONFIGURATION_ERROR': '保留verify-full；sslrootcert=system依赖客户端系统CA。自定义CA路径必须存在且来自Supabase官方，不能关闭校验。',
    'SCHEMA_VERSION_ERROR': '数据库已连接，但无法读取public.schema_migrations中的version=1；只读检查版本、表权限和原SQL是否完整提交，不重跑建表或盲目补版本。',
    'CONNECTED': 'DNS/TCP及带原配置的数据库连接、只读schema版本检查成功；未创建管理员或更改数据。',
    'OTHER_CONNECTION_ERROR': '核对项目运行状态、pooler状态及Supabase连接日志；只分享本诊断类别，不分享连接URL或异常原文。',
}

@dataclass(frozen=True)
class Diagnosis:
    category: str
    @property
    def advice(self):
        return ADVICE[self.category]
    @property
    def ok(self):
        return self.category == 'CONNECTED'

def classify_error(exc):
    """SQLSTATE first; libpq often provides no SQLSTATE for connect-time failures.

    Examine internal messages only for classification. Return exclusively allowlisted text.
    """
    pending = [exc]
    seen = set()
    messages, states, errors = [], set(), []
    while pending and len(seen) < 12:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        states.add(getattr(item, 'sqlstate', None))
        errors.append(item)
        children = [child for child in (getattr(item, 'orig', None), getattr(item, '__cause__', None))
                    if isinstance(child, BaseException)]
        # SQLAlchemy wrapper text may include URL parameter names such as sslrootcert.
        # Classify only leaf driver errors, never SQL/parameter context from wrappers.
        if not children:
            messages.append(str(item).lower())
        pending.extend(children)
    message = '\n'.join(messages)
    if '3D000' in states:
        return Diagnosis('DATABASE_NOT_FOUND')
    if any(s and s.startswith('28') for s in states):
        return Diagnosis('AUTHENTICATION_ERROR')
    if any(isinstance(e, socket.gaierror) for e in errors) or any(s in message for s in (
            'could not translate host name', 'name or service not known', 'temporary failure in name resolution', 'nodename nor servname')):
        return Diagnosis('DNS_ERROR')
    if any(s in message for s in ('certificate verify failed', 'certificate verification failed',
            'does not match host name', 'hostname mismatch', 'self-signed certificate', 'unable to get local issuer certificate', 'certificate has expired')):
        return Diagnosis('TLS_CERTIFICATE_ERROR')
    if any(s in message for s in ('root certificate file', 'sslrootcert', 'invalid sslmode', 'server does not support ssl', 'ssl is not enabled')):
        return Diagnosis('TLS_CONFIGURATION_ERROR')
    if any(s in message for s in ('password authentication failed', 'authentication failed',
            'sasl authentication', 'tenant or user not found', 'no pg_hba.conf entry')):
        return Diagnosis('AUTHENTICATION_ERROR')
    if 'database' in message and 'does not exist' in message:
        return Diagnosis('DATABASE_NOT_FOUND')
    if any(isinstance(e, (TimeoutError, ConnectionError)) or
           isinstance(e, OSError) and e.errno in (errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED, errno.ECONNRESET)
           for e in errors) or any(s in message for s in (
               'connection timed out', 'timeout expired', 'connection timeout', 'network is unreachable',
               'no route to host', 'connection refused', 'connection reset')):
        return Diagnosis('NETWORK_ERROR')
    return Diagnosis('OTHER_CONNECTION_ERROR')

def resolve(host, port, timeout=8):
    result = queue.Queue(maxsize=1)
    def worker():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except Exception as exc:
            result.put(exc)
    threading.Thread(target=worker, daemon=True).start()
    try:
        value = result.get(timeout=timeout)
    except queue.Empty:
        raise socket.gaierror('DNS lookup timed out') from None
    if isinstance(value, Exception):
        raise value
    return value

def tcp_probe(addresses, timeout=8):
    deadline = time.monotonic() + timeout
    error = TimeoutError()
    for family, socktype, proto, _, address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with socket.socket(family, socktype, proto) as conn:
                conn.settimeout(remaining)
                conn.connect(address)
                return
        except OSError as exc:
            error = exc
    raise error

def diagnose(database_url, *, network_probe=True, engine_factory=create_engine):
    try:
        url = make_url(database_url)
        if url.drivername != 'postgresql+psycopg' or not url.database or not url.username:
            return Diagnosis('CONFIGURATION_ERROR')
        # Supabase pooler configuration must be unambiguous; query args must not override it.
        if any(k in url.query for k in ('host', 'hostaddr', 'port', 'user', 'password', 'dbname', 'service', 'servicefile')) and network_probe:
            return Diagnosis('CONFIGURATION_ERROR')
        if network_probe:
            if not url.host or url.port not in (None, 5432):
                return Diagnosis('POOLER_CONFIGURATION_ERROR')
            if url.host.endswith('.pooler.supabase.com') and '.' not in url.username:
                return Diagnosis('POOLER_CONFIGURATION_ERROR')
            if url.query.get('sslmode') != 'verify-full':
                return Diagnosis('TLS_CONFIGURATION_ERROR')
            root = url.query.get('sslrootcert')
            if not isinstance(root, str) or (root != 'system' and not Path(root).is_file()):
                return Diagnosis('TLS_CONFIGURATION_ERROR')
    except Exception:
        return Diagnosis('CONFIGURATION_ERROR')
    if network_probe:
        try:
            addresses = resolve(url.host, url.port or 5432)
        except Exception:
            return Diagnosis('DNS_ERROR')
        try:
            tcp_probe(addresses)
        except Exception:
            return Diagnosis('NETWORK_ERROR')
    db = None
    try:
        # Same SQLAlchemy/psycopg path and TLS URL as the app. No fallback/weakening.
        db = engine_factory(database_url, poolclass=NullPool, echo=False, hide_parameters=True,
                            connect_args={'connect_timeout': 10}, execution_options={'postgresql_readonly': True})
        try:
            conn = db.connect()
        except Exception as exc:
            return classify_error(exc)
        with conn:
            try:
                # Version is public schema deliberately, independent of search_path.
                version = conn.scalar(text('SELECT version FROM public.schema_migrations WHERE version=1'))
                if version != 1:
                    return Diagnosis('SCHEMA_VERSION_ERROR')
            except Exception:
                return Diagnosis('SCHEMA_VERSION_ERROR')
        return Diagnosis('CONNECTED')
    except Exception as exc:
        return classify_error(exc)
    finally:
        if db is not None:
            try:
                db.dispose()
            except Exception:
                pass

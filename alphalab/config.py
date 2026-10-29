import os
from dataclasses import dataclass, field
from decimal import Decimal

class SetupRequired(Exception):
    pass

SAFE_CONFIGURATION_MESSAGE = '数据库安全连接配置未完成。请在部署平台配置官方 Supabase CA、DATABASE_URL 和 APP_SECRET_KEY；不要发送真实配置到聊天。'

class UserError(Exception):
    pass

@dataclass(frozen=True)
class Settings:
    database_url: str = field(default='', repr=False)
    supabase_ca_cert: str = field(default='', repr=False)
    app_secret_key: str = field(default='', repr=False)
    deepseek_api_key: str = field(default='', repr=False)
    deepseek_model: str = 'deepseek-chat'
    admin_phone: str = ''
    admin_initial_password: str = field(default='', repr=False)
    daily_calls: int = 30
    platform_daily_calls: int = 300
    daily_budget: Decimal = Decimal('20')
    input_price: Decimal = Decimal('2')
    output_price: Decimal = Decimal('3')
    session_hours: int = 12
    @classmethod
    def load(cls, secrets=None):
        values = {}
        for name in cls.__dataclass_fields__:
            key = name.upper()
            raw = os.environ.get(key)
            if raw is None and secrets is not None:
                try:
                    raw = secrets.get(key)
                except Exception:
                    raw = None
            if raw is not None:
                if name in ('daily_calls', 'platform_daily_calls', 'session_hours'):
                    raw = int(raw)
                if name in ('daily_budget', 'input_price', 'output_price'):
                    raw = Decimal(str(raw))
                values[name] = raw
        return cls(**values)
    def require_db(self):
        if not self.database_url:
            raise SetupRequired(SAFE_CONFIGURATION_MESSAGE)
        if not isinstance(self.database_url, str) or not self.database_url.startswith('postgresql+psycopg://'):
            raise SetupRequired('数据库安全连接配置未完成。DATABASE_URL 必须使用 postgresql+psycopg://。')
        from sqlalchemy.engine import make_url
        try:
            url=make_url(self.database_url)
        except Exception:
            raise SetupRequired('数据库安全连接配置未完成。请检查服务端连接配置。') from None
        local=url.host in ('localhost','127.0.0.1','::1') or (not url.host and str(url.query.get('host','')).startswith('/tmp/'))
        if not local and url.query.get('sslmode')!='verify-full':
            raise SetupRequired('数据库安全连接配置未完成。远程 PostgreSQL 连接需要 sslmode=verify-full 和官方 CA。')
        if not isinstance(self.app_secret_key, str) or len(self.app_secret_key) < 32 or 'replace' in self.app_secret_key.lower():
            raise SetupRequired('数据库安全连接配置未完成。APP_SECRET_KEY 需设置为至少32字符的随机密钥。')

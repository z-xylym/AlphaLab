import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import select, insert, update, delete, func
from .db import users, sessions, invitations, attempts, now, lock, engine
from .config import UserError

hasher = PasswordHasher(type=Type.ID)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))

def phone_number(value):
    value = value.strip().replace(' ', '').removeprefix('+86')
    if not re.fullmatch(r'1[3-9]\d{9}', value):
        raise UserError('请输入有效的中国大陆手机号。')
    return value

def password_ok(value):
    if len(value) < 12 or len(value) > 128:
        raise UserError('密码需要12～128个字符。')
    return value

class Auth:
    def __init__(self, settings):
        self.settings = settings
        self.db = engine(settings)
    def digest(self, value):
        return hmac.new(self.settings.app_secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    def principal(self, conn, token, admin=False):
        if not token:
            raise UserError('请先登录。')
        row = conn.execute(select(users).join(sessions, sessions.c.user_id == users.c.id).where(
            sessions.c.token_hash == self.digest(token), sessions.c.expires_at > now(), users.c.enabled.is_(True)
        )).mappings().first()
        if not row:
            raise UserError('会话已过期或账户已停用，请重新登录。')
        if admin and not row['is_admin']:
            raise UserError('需要管理员权限。')
        return row
    def current(self, token):
        with self.db.begin() as conn:
            return dict(self.principal(conn, token))
    def bootstrap(self):
        phone = phone_number(self.settings.admin_phone)
        password = password_ok(self.settings.admin_initial_password)
        if password.lower() in ('change_me', 'change_me_now', 'your_password'):
            raise UserError('请设置独立的管理员强密码。')
        with self.db.begin() as conn:
            lock(conn, 'bootstrap')
            if conn.scalar(select(func.count()).select_from(users).where(users.c.is_admin.is_(True))):
                return False
            if conn.scalar(select(users.c.id).where(users.c.phone == phone)):
                raise UserError('该手机号已存在，初始化不会提升已有用户权限。')
            conn.execute(insert(users).values(phone=phone, password_hash=hasher.hash(password), is_admin=True,
                                             daily_calls=self.settings.daily_calls))
            return True
    def login(self, phone, password):
        phone = phone_number(phone)
        key = self.digest('login:' + phone)
        token = None
        error = None
        with self.db.begin() as conn:
            lock(conn, 'login-global')
            recent = now() - timedelta(minutes=15)
            total = conn.scalar(select(func.coalesce(func.sum(attempts.c.failures), 0)).where(attempts.c.window_start > recent))
            row = conn.execute(select(attempts).where(attempts.c.key == key)).mappings().first()
            if total >= 100 or (row and row['window_start'] > recent and row['failures'] >= 5):
                error = '尝试次数过多，请15分钟后重试。'
            else:
                user = conn.execute(select(users).where(users.c.phone == phone)).mappings().first()
                try:
                    valid = hasher.verify(user['password_hash'] if user else DUMMY_HASH, password)
                except (VerificationError, InvalidHashError):
                    valid = False
                if user and valid and user['enabled']:
                    token = secrets.token_urlsafe(48)
                    conn.execute(insert(sessions).values(token_hash=self.digest(token), user_id=user['id'],
                        expires_at=now() + timedelta(hours=self.settings.session_hours)))
                    conn.execute(delete(attempts).where(attempts.c.key == key))
                    if hasher.check_needs_rehash(user['password_hash']):
                        conn.execute(update(users).where(users.c.id == user['id']).values(password_hash=hasher.hash(password)))
                else:
                    failures = row['failures'] + 1 if row and row['window_start'] > recent else 1
                    start = row['window_start'] if row and row['window_start'] > recent else now()
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    stmt = pg_insert(attempts).values(key=key, failures=failures, window_start=start)
                    conn.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={'failures': failures, 'window_start': start}))
                    error = '手机号或密码不正确，或账户已停用。'
        if error:
            raise UserError(error)
        return token
    def logout(self, token):
        with self.db.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == self.digest(token)))
    def change_password(self, token, old, new):
        password_ok(new)
        with self.db.begin() as conn:
            user = self.principal(conn, token)
            try:
                hasher.verify(user['password_hash'], old)
            except VerificationError:
                raise UserError('原密码错误。') from None
            conn.execute(update(users).where(users.c.id == user['id']).values(password_hash=hasher.hash(new)))
            conn.execute(delete(sessions).where(sessions.c.user_id == user['id']))
    def invite(self, token, phone):
        phone = phone_number(phone)
        code = secrets.token_urlsafe(24)
        with self.db.begin() as conn:
            admin = self.principal(conn, token, admin=True)
            conn.execute(insert(invitations).values(user_id=admin['id'], phone=phone, code_hash=self.digest(code),
                                                    expires_at=now() + timedelta(days=3)))
        return code
    def register(self, phone, password, code):
        phone = phone_number(phone)
        password_ok(password)
        with self.db.begin() as conn:
            lock(conn, 'register:' + phone)
            invite = conn.execute(select(invitations).where(invitations.c.phone == phone,
                invitations.c.code_hash == self.digest(code), invitations.c.used_at.is_(None),
                invitations.c.expires_at > now()).with_for_update()).mappings().first()
            if not invite or conn.scalar(select(users.c.id).where(users.c.phone == phone)):
                raise UserError('邀请无效、已过期，或手机号已注册。')
            conn.execute(insert(users).values(phone=phone, password_hash=hasher.hash(password), daily_calls=self.settings.daily_calls))
            conn.execute(update(invitations).where(invitations.c.id == invite['id']).values(used_at=now()))

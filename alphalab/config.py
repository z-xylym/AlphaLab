import os
from dataclasses import dataclass
from decimal import Decimal

class SetupRequired(Exception):
    pass

class UserError(Exception):
    pass

@dataclass(frozen=True)
class Settings:
    database_url: str = ''
    app_secret_key: str = ''
    deepseek_api_key: str = ''
    deepseek_model: str = 'deepseek-chat'
    admin_phone: str = ''
    admin_initial_password: str = ''
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
            raise SetupRequired('请先配置 Supabase DATABASE_URL，并执行数据库迁移。')
        if not self.database_url.startswith('postgresql+psycopg://'):
            raise SetupRequired('DATABASE_URL 必须使用 postgresql+psycopg://。')
        from sqlalchemy.engine import make_url
        url=make_url(self.database_url)
        local=url.host in ('localhost','127.0.0.1','::1') or (not url.host and str(url.query.get('host','')).startswith('/tmp/'))
        if not local and url.query.get('sslmode')!='verify-full':
            raise SetupRequired('远程 PostgreSQL 连接需要 sslmode=verify-full 和可信 CA。')
        if len(self.app_secret_key) < 32 or 'replace' in self.app_secret_key.lower():
            raise SetupRequired('APP_SECRET_KEY 需设置为至少32字符的随机密钥。')

from datetime import datetime, timezone
from functools import lru_cache
import uuid
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, Boolean, DateTime,
                        Numeric, ForeignKey, UniqueConstraint, Index, create_engine, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID

def now():
    return datetime.now(timezone.utc)

def today():
    from zoneinfo import ZoneInfo
    return now().astimezone(ZoneInfo('Asia/Shanghai')).date()

def uid():
    return uuid.uuid4()

metadata = MetaData()
users = Table('users', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uid),
    Column('phone', String(20), unique=True, nullable=False),
    Column('password_hash', Text, nullable=False),
    Column('is_admin', Boolean, nullable=False, default=False),
    Column('enabled', Boolean, nullable=False, default=True),
    Column('daily_calls', Integer, nullable=False, default=30),
    Column('created_at', DateTime(timezone=True), nullable=False, default=now))
sessions = Table('auth_sessions', metadata,
    Column('token_hash', String(64), primary_key=True),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False))
attempts = Table('login_attempts', metadata,
    Column('key', String(64), primary_key=True),
    Column('failures', Integer, nullable=False),
    Column('window_start', DateTime(timezone=True), nullable=False))
invitations = Table('invitations', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uid),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), nullable=False),
    Column('phone', String(20), nullable=False),
    Column('code_hash', String(64), unique=True, nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False),
    Column('used_at', DateTime(timezone=True)))
usage = Table('api_usage_logs', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uid),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), nullable=False),
    Column('request_key', String(64), nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, default=now),
    Column('status', String(20), nullable=False),
    Column('reserved_cost', Numeric(16,8), nullable=False),
    Column('cost', Numeric(16,8), nullable=False, default=0),
    Column('input_tokens', Integer, default=0), Column('output_tokens', Integer, default=0),
    Column('model', String(100), nullable=False), Column('response', Text),
    UniqueConstraint('user_id', 'request_key'))
cache = Table('public_cache', metadata,
    Column('key', String(200), primary_key=True),
    Column('payload', JSONB, nullable=False),
    Column('source', Text, nullable=False),
    Column('fetched_at', DateTime(timezone=True), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False))
# Documents keep versioned domain payloads while preserving database-level ownership.
PRIVATE_NAMES = ('user_preferences', 'chat_sessions', 'chat_messages', 'user_memories',
    'research_reports', 'watchlists', 'watchlist_items', 'portfolios', 'portfolio_positions',
    'simulated_trades', 'screening_runs', 'strategy_results')
private = {}
for name in PRIVATE_NAMES:
    private[name] = Table(name, metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uid),
        Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        Column('key', String(200), nullable=False),
        Column('payload', JSONB, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False, default=now),
        Column('updated_at', DateTime(timezone=True), nullable=False, default=now),
        UniqueConstraint('user_id', 'key'),
        Index(f'ix_{name}_owner_updated', 'user_id', 'updated_at'))
public = {}
for name in ('stock_master', 'stock_prices', 'industries', 'industry_members', 'policies', 'policy_industries'):
    public[name] = Table(name, metadata,
        Column('key', String(200), primary_key=True), Column('payload', JSONB, nullable=False),
        Column('source', Text, nullable=False), Column('fetched_at', DateTime(timezone=True), nullable=False))
Index('ix_usage_owner_date', usage.c.user_id, usage.c.created_at)
Index('ix_usage_date', usage.c.created_at)
Index('ix_sessions_expiry', sessions.c.expires_at)

@lru_cache(maxsize=4)
def engine_for(url):
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                         connect_args={'connect_timeout': 10}, hide_parameters=True)

def engine(settings):
    settings.require_db()
    return engine_for(settings.database_url)

def lock(conn, name):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))'), {'name': name})

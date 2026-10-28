from sqlalchemy import select, delete, update
from sqlalchemy.dialects.postgresql import insert
from .db import private, users, sessions, usage, cache, now, lock
from .config import UserError

class Repository:
    """All private operations resolve a live server-issued session; callers cannot supply user_id."""
    def __init__(self, auth, token):
        self.auth, self.token, self.db = auth, token, auth.db
    def _list(self, conn, table, key=None, limit=100):
        user = self.auth.principal(conn, self.token)
        t = private[table]
        q = select(t).where(t.c.user_id == user['id'])
        if key is not None:
            q = q.where(t.c.key == key)
        return [dict(r) for r in conn.execute(q.order_by(t.c.updated_at.desc()).limit(limit)).mappings()]
    def list(self, table, key=None, limit=100):
        with self.db.begin() as conn:
            return self._list(conn, table, key, limit)
    def get(self, table, key, default=None):
        rows = self.list(table, key)
        return rows[0]['payload'] if rows else default
    def _put(self, conn, table, key, payload):
        user = self.auth.principal(conn, self.token)
        t = private[table]
        stmt = insert(t).values(user_id=user['id'], key=key, payload=payload)
        conn.execute(stmt.on_conflict_do_update(index_elements=['user_id', 'key'],
                     set_={'payload': payload, 'updated_at': now()}))
    def put(self, table, key, payload):
        if len(key) > 200:
            raise UserError('记录标识过长。')
        with self.db.begin() as conn:
            self._put(conn, table, key, payload)
    def remove(self, table, key=None):
        with self.db.begin() as conn:
            user = self.auth.principal(conn, self.token)
            t = private[table]
            q = delete(t).where(t.c.user_id == user['id'])
            if key is not None:
                q = q.where(t.c.key == key)
            conn.execute(q)
    def memory(self, query, limit=8):
        terms = [x.lower() for x in query.split() if x]
        records = self.list('user_memories', limit=30) + self.list('research_reports', limit=30)
        ranked = sorted(records, key=lambda r: sum(t in str(r['payload']).lower() for t in terms), reverse=True)
        return [{'saved_at': str(r['created_at']), 'historical_only': True, 'data': r['payload']} for r in ranked[:limit]]
    def admin_users(self):
        with self.db.begin() as conn:
            self.auth.principal(conn, self.token, admin=True)
            return [dict(r) for r in conn.execute(select(users.c.id, users.c.phone, users.c.enabled,
                     users.c.is_admin, users.c.daily_calls, users.c.created_at)).mappings()]
    def admin_update(self, user_id, enabled, daily_calls):
        if not 0 <= daily_calls <= 10000:
            raise UserError('每日额度需为0～10000。')
        with self.db.begin() as conn:
            self.auth.principal(conn, self.token, admin=True)
            lock(conn, 'admin-users')
            target = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not target or target['is_admin']:
                raise UserError('此入口不能修改管理员。')
            conn.execute(update(users).where(users.c.id == user_id).values(enabled=enabled, daily_calls=daily_calls))
            if not enabled:
                conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
    def admin_usage(self):
        with self.db.begin() as conn:
            self.auth.principal(conn, self.token, admin=True)
            return [dict(r) for r in conn.execute(select(usage.c.user_id, usage.c.created_at, usage.c.status,
                usage.c.input_tokens, usage.c.output_tokens, usage.c.cost, usage.c.reserved_cost).order_by(usage.c.created_at.desc()).limit(300)).mappings()]
    def clear_cache(self):
        with self.db.begin() as conn:
            self.auth.principal(conn, self.token, admin=True)
            conn.execute(delete(cache))

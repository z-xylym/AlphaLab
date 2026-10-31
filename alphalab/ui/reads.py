"""UI-only public read model. No provider, auth, private-data or schema changes."""
import time
import streamlit as st
from sqlalchemy import select
from ..data import MarketData, DataUnavailable
from ..db import cache, now


def remember(key, loader, ttl=30):
    # Public data only, bounded to this browser session; never cache authorization.
    entries = st.session_state.setdefault('_public_views', {})
    previous = entries.get(key)
    if previous and time.monotonic() - previous[0] < ttl:
        return previous[1]
    try:
        result = loader()
    except DataUnavailable:
        result = None
    if len(entries) >= 48:
        entries.pop(next(iter(entries)))
    entries[key] = (time.monotonic(), result)
    return result


def invalidate():
    st.session_state.pop('_public_views', None)


class CachedResearch(MarketData):
    """Use existing persisted public payloads until the user explicitly updates."""

    def security_master(self, exchange=None, refresh=False, cached_only=True):
        if refresh:
            result = super().security_master(exchange, refresh=True)
            invalidate()
            return result
        result = remember(('master', exchange),
                          lambda: super(CachedResearch, self).security_master(exchange, cached_only=True))
        if result is None:
            raise DataUnavailable('基础名单尚未准备好，请联系管理员更新。')
        return result

    def financials(self, code, refresh=False):
        if refresh:
            return super().financials(code, refresh=True)
        return self._read('financial:'+code)

    def business(self, code, refresh=False):
        if refresh:
            return super().business(code, refresh=True)
        return self._read('business:'+code)

    def _read(self, key):
        result = remember(key, lambda: self.cache_only(key))
        if result is None:
            raise DataUnavailable('尚未取得数据。')
        return result

    def history(self, code, start='20200101', end=None, refresh=False):
        if refresh:
            return super().history(code, start, end, refresh=True)
        def read():
            with self.db.connect() as conn:
                query = select(cache).where(cache.c.key.startswith(f'history:{code}:{start}:'))
                if end:
                    query = query.where(cache.c.key == f'history:{code}:{start}:{end}')
                row = conn.execute(query.order_by(cache.c.fetched_at.desc()).limit(1)).mappings().first()
            if not row:
                raise DataUnavailable('尚未取得日线。')
            return dict(row['payload'], source=row['source'], fetched_at=row['fetched_at'].isoformat(),
                        stale=row['expires_at'] <= now())
        result = remember(('history', code, start, end), read)
        if result is None:
            raise DataUnavailable('尚未取得日线。')
        return result


def cached_catalog(db):
    from ..personalization import data_version, industry_catalog
    version = data_version(db, ('master:', 'members:False:', 'sectors:False', 'spot:v1'))
    return remember(('industry_catalog', version), lambda: industry_catalog(db), ttl=1800), version

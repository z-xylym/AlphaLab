"""Isolated UI render timing and no-network evidence; never touches production databases."""
import json
import os
from pathlib import Path
import secrets
import statistics
import tempfile
import time
from unittest.mock import patch

import pgserver
from sqlalchemy import event
from streamlit.testing.v1 import AppTest

from alphalab import provider
from alphalab.ai_provider import DeepSeekClient
from alphalab.auth import Auth
from alphalab.config import Settings
from alphalab.db import metadata, engine_for
from alphalab.repository import Repository
import alphalab.ui as ui
from scripts.browser_check import seed


def main():
    root = Path.cwd()
    pg = pgserver.get_server(Path(tempfile.mkdtemp(prefix='alphalab-perf-')), cleanup_mode='delete')
    url = pg.get_uri().replace('postgresql://', 'postgresql+psycopg://', 1)
    settings = Settings(database_url=url, app_secret_key=secrets.token_hex(32),
                        admin_phone='13800000009', admin_initial_password=secrets.token_urlsafe(24))
    db = engine_for(url)
    metadata.create_all(db)
    auth = Auth(settings)
    auth.bootstrap()
    token = auth.login(settings.admin_phone, settings.admin_initial_password)
    seed(auth, token)
    repo = Repository(auth, token)
    repo.put('user_preferences', 'profile', {'level': '零基础', 'industries': [],
             'period': '长期', 'goal': '核对稳健经营', 'onboarding_completed': True})
    records = []
    queries = []
    upstream = []
    def forbidden(*a, **k):
        upstream.append('attempt')
        raise AssertionError('No external requests during ordinary browsing')
    def query(conn, cursor, statement, *args):queries.append(statement)
    def timed(name, fn):
        def call(*a, **k):
            started = time.perf_counter(); count = len(queries)
            result = fn(*a, **k)
            records.append({'page': name, 'ms': round((time.perf_counter()-started)*1000, 2),
                            'queries': len(queries)-count})
            return result
        return call
    event.listen(db, 'before_cursor_execute', query)
    runtime_env = {'DATABASE_URL': url, 'APP_SECRET_KEY': settings.app_secret_key, 'DEEPSEEK_API_KEY': ''}
    from alphalab import data
    with patch.dict(os.environ, runtime_env), patch.object(provider, 'call', forbidden), \
         patch.object(data, 'fetch_policy_index', forbidden), patch.object(DeepSeekClient, 'complete', forbidden), \
         patch.object(ui, 'home', timed('home', ui.home)), patch.object(ui, 'stock_research', timed('stock', ui.stock_research)):
        app = AppTest.from_file(str(root/'app.py'))
        app.session_state['token'] = token
        def checked():
            assert not app.exception and not app.error
        app.run(timeout=30); checked()
        for _ in range(3):app.run(timeout=30); checked()
        app.radio(key='navigation').set_value('个股')
        app.session_state['research_query'] = '600519'
        app.session_state['stock_query'] = '600519'
        app.run(timeout=30); checked()
        for _ in range(3):app.run(timeout=30); checked()
        overview = records[-4:]
        app.radio(key='research_tab').set_value('财务').run(timeout=30); checked()
        for _ in range(3):app.run(timeout=30); checked()
        financial = records[-4:]
        for tab in ('主营', 'AI研究', '走势', '预警'):
            app.radio(key='research_tab').set_value(tab).run(timeout=30); checked()
        for page in ('自选', 'AI研究', '市场', '我的', '首页'):
            app.radio(key='navigation').set_value(page).run(timeout=30); checked()
    event.remove(db, 'before_cursor_execute', query)
    def metric(rows):
        return {'cold_ms': rows[0]['ms'], 'rerun_ms_median': statistics.median(r['ms'] for r in rows[1:]),
                'cold_queries': rows[0]['queries'], 'rerun_queries': rows[-1]['queries']}
    result = {'fixture_only': True, 'measurement': 'server UI function render, excludes AppTest orchestration',
              'home': metric(records[:4]), 'overview': metric(overview), 'financial': metric(financial),
              'external_attempts': len(upstream)}
    assert not upstream
    output = root/'test-results'
    output.mkdir(exist_ok=True)
    (output/'v12-performance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':main()

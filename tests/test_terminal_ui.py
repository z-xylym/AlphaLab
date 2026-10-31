"""UI behavior and cache read boundaries; all financial fixtures are test-only."""
from datetime import timedelta
import pytest
from sqlalchemy import update
from streamlit.testing.v1 import AppTest

from alphalab import provider
from alphalab.ai import AI
from alphalab.data import MarketData
from alphalab.db import cache, now, today
from alphalab.ui.reads import CachedResearch


def seed_research(auth):
    data = MarketData(auth.db)
    fixture_source = '测试夹具：证券名单，非生产行情'
    data.cached('master:v1:SH', 86400, fixture_source, lambda: {
        'items': [{'code': '600519', 'name': '贵州茅台', 'exchange': 'SH', 'price': None,
                   'listing_date': '2001-08-27', 'industry': '测试行业，非生产分类'}]}, 'stock_master')
    data.cached('history:600519:20200101:'+today().strftime('%Y%m%d'), 3600, '测试夹具日线', lambda: {
        'items': [{'date': str(today()-timedelta(days=2)), 'close': 100, 'open': 100, 'low': 99, 'high': 101, 'volume': 100},
                  {'date': str(today()-timedelta(days=1)), 'close': 101, 'open': 100, 'low': 99, 'high': 102, 'volume': 200}],
        'provider': '新浪不复权日线（测试夹具）'})
    data.cached('financial:600519', 3600, '新浪财务摘要（测试夹具）', lambda: {
        'items': [{'指标': label, '20251231': value} for label, value in (
            ('营业收入(元)', 100), ('归母净利润(元)', 20), ('净资产收益率(ROE)(%)', 10),
            ('销售毛利率(%)', 50), ('资产负债率(%)', 30), ('经营活动产生的现金流量净额(元)', 15))]})
    data.cached('business:600519', 3600, '东方财富主营（测试夹具）', lambda: {
        'items': [{'主营构成': '测试产品，非生产披露', '分类类型': '按产品', '主营收入': 100, '报告日期': '2025-12-31'}]})


def launch(system, monkeypatch):
    settings, _, _, user = system
    monkeypatch.setenv('DATABASE_URL', settings.database_url)
    monkeypatch.setenv('APP_SECRET_KEY', settings.app_secret_key)
    app = AppTest.from_file('app.py')
    app.session_state['token'] = user.token
    app.run(timeout=20)
    return app


def search(app, query='600519'):
    app.radio(key='navigation').set_value('个股').run(timeout=20)
    app.text_input(key='stock_query').input(query)
    next(x for x in app.button if x.label == '搜索').click().run(timeout=20)
    return app


def test_no_upstream_on_initial_home_or_search_without_cache(system, monkeypatch):
    seen = []
    def forbidden(*args, **kwargs):
        seen.append(args)
        raise AssertionError('Implicit upstream access')
    monkeypatch.setattr(provider, 'call', forbidden)
    app = launch(system, monkeypatch)
    assert not app.error and not app.warning and not app.exception
    assert any(x.value == '市场概览' for x in app.header)
    assert not any(x.label == '退出登录' for x in app.button)
    search(app)
    assert not app.error and not app.warning and not app.exception
    assert not seen


def test_cached_stock_lazy_views_and_reruns_do_not_refetch(system, monkeypatch):
    _, auth, _, _ = system
    seed_research(auth)
    upstream = []
    def forbidden(*args, **kwargs):
        upstream.append(args)
        raise RuntimeError('SECRET upstream details')
    monkeypatch.setattr(provider, 'call', forbidden)
    reads = []
    original = CachedResearch._read
    def tracked(self, key):
        reads.append(key)
        return original(self, key)
    monkeypatch.setattr(CachedResearch, '_read', tracked)
    app = search(launch(system, monkeypatch))
    assert not app.exception and not app.error
    assert any(x.value == '贵州茅台' for x in app.header)
    assert 'business:600519' not in reads
    assert not app.get('plotly_chart')
    app.radio(key='research_tab').set_value('走势').run(timeout=20)
    assert len(app.get('plotly_chart')) == 1
    app.radio(key='research_tab').set_value('主营').run(timeout=20)
    assert 'business:600519' in reads and len(app.dataframe) == 1
    assert not app.get('plotly_chart')
    app.radio(key='research_tab').set_value('财务').run(timeout=20)
    assert not app.exception and not app.error and not upstream
    # A server-side session check still runs on every rerun despite public view memoization.
    auth.logout(system[3].token)
    app.run(timeout=20)
    assert app.warning and not any(x.value == '贵州茅台' for x in app.header)


def test_explicit_refresh_is_only_upstream_trigger_and_invalidates_views(system, monkeypatch):
    import pandas as pd
    _, auth, _, _ = system
    seed_research(auth)
    app = search(launch(system, monkeypatch))
    calls = []
    def call(name, **kwargs):
        calls.append(name)
        if name == 'stock_zh_a_daily':
            return pd.DataFrame([{'date': str(today()), 'close': 105, 'open': 100, 'high': 106, 'low': 99, 'volume': 100}])
        if name == 'sina_financial_summary':
            return pd.DataFrame([{'指标': '营业收入(元)', '20251231': 120}])
        if name == 'stock_zygc_em':
            return pd.DataFrame([{'主营构成': '更新测试产品', '报告日期': '2025-12-31', '主营收入': 120}])
        pytest.fail('Unexpected provider')
    monkeypatch.setattr(provider, 'call', call)
    next(x for x in app.button if x.label == '更新研究数据').click().run(timeout=20)
    assert set(calls) == {'stock_zh_a_daily', 'sina_financial_summary', 'stock_zygc_em'}
    assert any(x.value == '研究数据已更新' for x in app.success)
    app.radio(key='research_tab').set_value('走势').run(timeout=20)
    assert not app.exception and len(calls) == 3
    assert any(str(today()) in x.value for x in app.caption)


def test_module_failure_does_not_block_other_panels_or_leak(system, monkeypatch):
    _, auth, _, _ = system
    seed_research(auth)
    # Missing business cache must not issue a replacement upstream call.
    from sqlalchemy import delete
    with auth.db.begin() as conn:
        conn.execute(delete(cache).where(cache.c.key == 'business:600519'))
        conn.execute(update(cache).where(cache.c.key == 'financial:600519').values(expires_at=now()-timedelta(seconds=1)))
    monkeypatch.setattr(provider, 'call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('SECRET_URL_COOKIE')))
    app = search(launch(system, monkeypatch))
    app.radio(key='research_tab').set_value('主营').run(timeout=20)
    assert not app.exception and not app.error
    app.radio(key='research_tab').set_value('AI研究').run(timeout=20)
    captured = []
    def generate(self, context, regenerate=False):
        import json
        from alphalab.company_report import payload, SECTIONS
        captured.append(context)
        answer=json.dumps({'sections':[{'title':title,'facts':[],'analysis':['测试报告，非投资建议'],'missing_data':[]} for title in SECTIONS]})
        return payload(context,answer,self.settings.deepseek_model,now().isoformat()),False
    monkeypatch.setattr(AI, 'company_summary', generate)
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-not-real-key')
    app.run(timeout=20)
    next(x for x in app.button if x.label == '生成AI研究').click().run(timeout=20)
    assert captured[0]['business_composition']['missing']
    assert captured[0]['financial_summary']['营业收入']['stale'] is True
    assert captured[0]['price_history_summary']['value'] and captured[0]['security']['code']['value']=='600519'
    assert not app.warning and not app.error


def test_latest_persisted_history_is_available_across_calendar_days(system, monkeypatch):
    _, auth, _, _ = system
    seed_research(auth)
    with auth.db.begin() as conn:
        conn.execute(update(cache).where(cache.c.key.startswith('history:600519:')).values(
            key='history:600519:20200101:20261001', expires_at=now()-timedelta(days=1)))
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('No automatic upstream'))
    app = search(launch(system, monkeypatch))
    app.radio(key='research_tab').set_value('走势').run(timeout=20)
    assert len(app.get('plotly_chart')) == 1 and not app.exception


def test_public_session_views_skip_repeated_cache_queries(system, monkeypatch):
    _, auth, _, _ = system
    seed_research(auth)
    keys = []
    original = CachedResearch.cache_only
    def read(self, key, **kwargs):
        keys.append(key)
        return original(self, key, **kwargs)
    monkeypatch.setattr(CachedResearch, 'cache_only', read)
    app = search(launch(system, monkeypatch))
    first = list(keys)
    app.radio(key='research_tab').set_value('财务').run(timeout=20)
    app.radio(key='research_tab').set_value('概览').run(timeout=20)
    assert keys == first
    assert keys.count('master:v1:SH') == 1 and keys.count('financial:600519') == 1
    assert not app.exception


def test_metadata_and_metrics_escape_dynamic_html_and_hide_raw_source(monkeypatch):
    from alphalab.ui import components
    output = []
    monkeypatch.setattr(components.st, 'html', output.append)
    components.data_meta({'source': 'https://secret.invalid/?password=PRIVATE',
                          'fetched_at': 'secret-cookie-value', 'stale': True})
    components.metric_grid([('<script>alert(1)</script>', '<img src=x>', '<b>bad</b>', '')])
    assert 'PRIVATE' not in output[0] and 'secret.invalid' not in output[0]
    assert 'secret-cookie-value' not in output[0] and '历史缓存' in output[0]
    assert '<script>' not in output[1] and '<img src=x>' not in output[1]
    assert '&lt;script&gt;' in output[1]


def test_company_ai_keyless_no_automatic_calls_persistence_and_failure(system, monkeypatch):
    import json
    import httpx
    from alphalab.company_report import SECTIONS
    _, auth, _, user = system
    seed_research(auth)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('AI tab must not fetch live market data'))
    calls=[]
    fail=[False]
    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers['Authorization']=='Bearer test-not-real-key'
        if fail[0]:return httpx.Response(500,text='PRIVATE_PROVIDER_BODY')
        from test_v12_research import summary_text
        answer=summary_text('UI隔离测试报告，非投资结论')
        return httpx.Response(200,json={'choices':[{'message':{'content':answer},'finish_reason':'stop'}],
                                        'usage':{'prompt_tokens':100,'completion_tokens':200}})
    original=AI.__init__
    def initialize(self,repo,settings,**kwargs):
        original(self,repo,settings,lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(AI,'__init__',initialize)
    app=search(launch(system,monkeypatch))
    app.radio(key='research_tab').set_value('AI研究').run(timeout=20)
    assert not app.exception and not app.error
    assert any('AI研究服务尚未配置' in x.value for x in app.info)
    assert next(x for x in app.button if x.label=='生成AI研究').disabled
    assert not calls
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-not-real-key')
    app.run(timeout=20)
    assert not calls
    next(x for x in app.button if x.label=='生成AI研究').click().run(timeout=20)
    assert not app.exception and not app.error and len(calls)==1
    assert '精简研究摘要' in {x.value for x in app.subheader}
    assert not (set(SECTIONS) & {x.value for x in app.subheader})
    assert any('生成时间' in x.value for x in app.caption)
    app.run(timeout=20)
    assert len(calls)==1 and '精简研究摘要' in {x.value for x in app.subheader}
    next(x for x in app.button if x.label=='生成AI研究').click().run(timeout=20)
    assert len(calls)==1
    next(x for x in app.button if x.label=='重新生成AI研究').click().run(timeout=20)
    assert len(calls)==2
    fail[0]=True
    next(x for x in app.button if x.label=='重新生成AI研究').click().run(timeout=20)
    assert len(calls)==3 and app.warning and not app.exception and not app.error
    assert '精简研究摘要' in {x.value for x in app.subheader}
    assert not (set(SECTIONS) & {x.value for x in app.subheader})
    assert 'PRIVATE_PROVIDER_BODY' not in '\n'.join(x.value for x in app.warning)
    reports=[row['payload'] for row in user.list('research_reports') if row['payload'].get('purpose')=='company_summary']
    assert len(reports)==1 and reports[0]['context_snapshot']['security']['code']['value']=='600519'

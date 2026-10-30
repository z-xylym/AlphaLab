"""V1.1 UI navigation and cache-only boundaries, with isolated user fixtures."""
import json
import pytest
from streamlit.testing.v1 import AppTest
from alphalab import provider
from alphalab.data import MarketData
from alphalab.company_report import payload, SECTIONS
from alphalab.research_context import build_context
from alphalab.db import now
from alphalab.ai import AI


def launch(system, monkeypatch):
    settings, auth, admin, user=system
    monkeypatch.setenv('DATABASE_URL',settings.database_url)
    monkeypatch.setenv('APP_SECRET_KEY',settings.app_secret_key)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.setattr(provider,'call',lambda *a,**k:pytest.fail('UI must never request upstream implicitly'))
    monkeypatch.setattr(AI,'company_report',lambda *a,**k:pytest.fail('Navigation must not call AI'))
    MarketData(auth.db).cached('master:v1:SH',3600,'证券名单测试夹具',lambda:{'items':[
        {'code':'600519','name':'测试公司','exchange':'SH','price':None}]},'stock_master')
    user.put('watchlist_items','600519',{'code':'600519','name':'测试公司'})
    context=build_context({'code':'600519','name':'测试公司','exchange':'SH'})
    answer=json.dumps({'sections':[{'title':title,'facts':[], 'analysis':['仅用于界面测试的分析'], 'missing_data':['缺少财务']} for title in SECTIONS]})
    report=payload(context,answer,'deepseek-chat',now().isoformat())
    user.put('research_reports','ui-report',report)
    admin.put('research_reports','other-user',dict(report,question='OTHER_USER_PRIVATE_REPORT'))
    app=AppTest.from_file('app.py')
    app.session_state['token']=user.token
    app.run(timeout=20)
    return app,user


def test_six_routes_watchlist_to_stock_and_planned_alerts(system,monkeypatch):
    app,user=launch(system,monkeypatch)
    assert app.radio(key='navigation').options==['首页','市场','自选','个股','AI研究','我的']
    assert not app.error and not app.exception
    app.radio(key='navigation').set_value('自选').run(timeout=20)
    assert any('研究已保存' in x.proto.body for x in app.get('html'))
    next(x for x in app.button if x.label=='查看研究').click().run(timeout=20)
    assert app.radio(key='navigation').value=='个股'
    assert app.text_input(key='stock_query').value=='600519'
    assert app.radio(key='research_tab').options==['概览','走势','财务','主营','AI研究','预警']
    app.radio(key='research_tab').set_value('预警').run(timeout=20)
    assert any('尚未启用' in x.value for x in app.caption)
    assert not app.error and not app.exception
    assert len(user.list('watchlist_items'))==1
    app.radio(key='navigation').set_value('自选').run(timeout=20)
    next(x for x in app.button if x.label=='移出自选').click().run(timeout=20)
    assert user.list('watchlist_items')==[]


def test_library_reads_nine_sections_private_search_and_disabled_followup(system,monkeypatch):
    app,user=launch(system,monkeypatch)
    app.radio(key='navigation').set_value('AI研究').run(timeout=20)
    assert 'OTHER_USER_PRIVATE_REPORT' not in '\n'.join(x.proto.body for x in app.get('html'))
    next(x for x in app.button if x.label=='阅读报告').click().run(timeout=20)
    assert set(SECTIONS)<={x.value for x in app.subheader}
    assert any(x.disabled for x in app.text_area if x.label=='围绕本报告继续研究')
    app.run(timeout=20)
    assert not app.error and not app.exception
    app.text_input[0].input('没有匹配公司').run(timeout=20)
    assert not any(x.label=='阅读报告' for x in app.button)
    assert '研究摘要' not in {x.value for x in app.subheader}


def test_market_keeps_industry_and_screening_as_second_level(system,monkeypatch):
    app,_=launch(system,monkeypatch)
    app.radio(key='navigation').set_value('市场').run(timeout=20)
    assert app.radio(key='market_section').options==['市场概览','行业观察','选股观察']
    app.radio(key='market_section').set_value('行业观察').run(timeout=20)
    assert not app.exception
    app.radio(key='market_section').set_value('选股观察').run(timeout=20)
    assert any(x.label=='生成观察名单' for x in app.button)
    assert not app.error and not app.exception

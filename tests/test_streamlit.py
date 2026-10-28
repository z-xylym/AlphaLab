from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_configuration_missing_is_explicit(monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    app=AppTest.from_file('app.py').run(timeout=15)
    assert not app.exception
    assert any('DATABASE_URL' in item.value for item in app.warning)

def test_login_home_navigation_and_no_private_access(system,monkeypatch):
    settings,auth,a,b=system
    monkeypatch.setenv('DATABASE_URL',settings.database_url)
    monkeypatch.setenv('APP_SECRET_KEY',settings.app_secret_key)
    app=AppTest.from_file('app.py').run(timeout=20)
    assert not app.exception
    assert len(app.text_input)>=5
    assert any(x.label=='手机号' for x in app.text_input)
    # Avoid external services for UI contract test; no fixture is used in real app.
    from alphalab.data import MarketData,DataUnavailable
    def fail(*args,**kwargs):raise DataUnavailable('测试：源不可用')
    for name in ('indices','spot','policies'):monkeypatch.setattr(MarketData,name,fail)
    app.session_state['token']=b.token
    app.run(timeout=20)
    assert not app.exception
    assert app.selectbox[0].options==['首页','行业','选股','个股','我的']
    app.selectbox[0].select('我的').run(timeout=20)
    assert '管理后台' not in app.selectbox[1].options
    assert not app.exception

def test_research_industry_screen_and_private_screens(system,monkeypatch):
    from alphalab.data import MarketData
    from alphalab.ai import AI
    from alphalab.db import today
    from datetime import timedelta
    settings,auth,a,b=system
    monkeypatch.setenv('DATABASE_URL',settings.database_url)
    monkeypatch.setenv('APP_SECRET_KEY',settings.app_secret_key)
    stock={'code':'600001','name':'测试夹具公司','price':11,'change_pct':2,'turnover':100000000,'pe':10,'pb':1}
    def envelope(items,**extra):
        return {'items':items,'source':'自动化测试夹具，非真实行情','fetched_at':'2026-01-01T00:00:00+00:00','stale':False,**extra}
    monkeypatch.setattr(MarketData,'spot',lambda self:envelope([stock]))
    monkeypatch.setattr(MarketData,'indices',lambda self:envelope([dict(stock,date='2026-01-01')]))
    monkeypatch.setattr(MarketData,'policies',lambda self:envelope([]))
    monkeypatch.setattr(MarketData,'sectors',lambda self,*a:envelope([{'name':'测试行业'}]))
    monkeypatch.setattr(MarketData,'members',lambda self,*a:envelope([stock]))
    monkeypatch.setattr(MarketData,'company',lambda self,code:envelope([{'行业':'测试行业','上市时间':'20200101'}]))
    monkeypatch.setattr(MarketData,'business',lambda self,code:envelope([{'主营构成':'测试产品','报告日期':'2025-12-31','主营收入':100}]))
    monkeypatch.setattr(MarketData,'financials',lambda self,code:envelope([{'指标':'营业收入','20251231':100}]))
    bars=[{'date':str(today()-timedelta(days=160-i)),'open':10+i*.01,'close':10+i*.01,'high':11+i*.01,'low':9+i*.01,'volume':1000} for i in range(160)]
    monkeypatch.setattr(MarketData,'history',lambda self,*a:envelope(bars))
    monkeypatch.setattr(AI,'generate',lambda *a,**k:('已核实事实：自动化测试夹具。',False))
    app=AppTest.from_file('app.py');app.session_state['token']=b.token;app.run(timeout=20)
    assert not app.exception and not app.error
    app.selectbox[0].select('行业').run(timeout=20)
    assert not app.exception and not app.error
    app.selectbox[0].select('选股').run(timeout=20)
    next(x for x in app.button if x.label=='生成观察名单').click().run(timeout=20)
    assert not app.exception and not app.error and b.list('screening_runs')
    app.selectbox[0].select('个股').run(timeout=20)
    app.text_input[0].input('测试').run(timeout=20)
    assert not app.exception and not app.error
    next(x for x in app.button if x.label=='加入自选').click().run(timeout=20)
    assert b.get('watchlist_items','600001')['name']=='测试夹具公司'
    next(x for x in app.button if x.label=='生成AI研究报告').click().run(timeout=20)
    assert any('自动化测试夹具' in x.value for x in app.markdown)
    app.selectbox[0].select('我的').run(timeout=20)
    for section in ['自选','聊天','研究历史','模拟交易','策略回测','个人设置','记忆管理']:
        app.selectbox[1].select(section).run(timeout=20)
        assert not app.exception and not app.error,section

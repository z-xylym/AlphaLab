"""Real product flows backed by disposable PostgreSQL and explicitly synthetic research fixtures."""
import json
from sqlalchemy import select
from streamlit.testing.v1 import AppTest
import pytest
from alphalab.personalization import industry_catalog, recommend
from alphalab.data import MarketData
from alphalab.ai import AI
from alphalab import provider
from alphalab.company_report import SYSTEM, VERSION


def seed(auth):
    data=MarketData(auth.db)
    rows=[{'code':'600001','name':'观察食品甲（夹具）','industry':'食品饮料'},
          {'code':'000001','name':'观察银行乙（夹具）','industry':'银行'},
          {'code':'600002','name':'观察食品丙（夹具）','industry':'食品饮料'},
          {'code':'600003','name':'分类缺失丁（夹具）'}]
    for exchange,prefix in [('SH','6'),('SZ','0')]:
        data.cached('master:v1:'+exchange,3600,'证券名单隔离测试夹具',lambda prefix=prefix:{'items':[dict(r,exchange=exchange) for r in rows if r['code'].startswith(prefix)]},'stock_master')
    for code in ('600001','000001'):
        data.cached('financial:'+code,3600,'财报隔离测试夹具',lambda:{'items':[
            {'指标':'净利润（元）','20260930':100},{'指标':'净资产收益率（%）','20260930':12},
            {'指标':'经营活动产生的现金流量净额（元）','20260930':90}]})
    data.cached('spot:v1',3600,'行情隔离测试夹具',lambda:{'items':[{'code':'000001','price':10,'change_pct':1.2}]})
    data.cached('sectors:False',3600,'行业隔离测试夹具',lambda:{'items':[{'name':'公用事业'}]})
    data.cached('members:False:公用事业',3600,'行业成分隔离测试夹具',lambda:{'items':[{'code':'600004','name':'公用事业戊（夹具）'}]})


def profile(**changes):
    return {'level':'零基础','industries':['食品饮料','银行'],'period':'长期',
            'goal':'想找经营稳健、适合长期观察的公司。','onboarding_completed':True,**changes}


def test_rules_have_explicit_industries_and_no_guessing(system,monkeypatch):
    settings,auth,admin,user=system;seed(auth)
    monkeypatch.setattr(provider,'call',lambda *a,**k:pytest.fail('No upstream for recommendations'))
    catalog=industry_catalog(auth.db)
    assert set(catalog['industries'])=={'食品饮料','银行','公用事业'}
    assert '600003' not in {code for codes in catalog['industries'].values() for code in codes}
    rows=recommend(auth.db,profile(),catalog)
    assert [row['code'] for row in rows]==['600001','000001','600002']
    assert rows[0]['positive_observation'] and rows[1]['positive_observation']
    assert not rows[2]['positive_observation'] and '尚未核实' in rows[2]['risk']
    assert '稳健' in rows[0]['reason'] and '长期' in rows[0]['reason']
    assert rows[0]['quote']=={} and rows[1]['quote']['price']==10
    assert rows[0]['financial_period']=='20260930'
    assert recommend(auth.db,profile(industries=['不存在的行业']),catalog)==[]
    assert recommend(auth.db,{'level':'零基础'},catalog)==[]
    admin.put('user_preferences','profile',profile(industries=['公用事业']))
    user.put('user_preferences','profile',profile())
    assert recommend(auth.db,admin.get('user_preferences','profile'),catalog)[0]['code']=='600004'
    assert user.get('user_preferences','profile')['industries']==['食品饮料','银行']


def test_quality_does_not_mix_report_periods_and_short_period_uses_history(system):
    _,auth,_,_=system;seed(auth);data=MarketData(auth.db)
    with auth.db.begin() as conn:
        from alphalab.db import cache
        conn.execute(cache.update().where(cache.c.key=='financial:600001').values(payload={'items':[
            {'指标':'净利润','20260930':100},{'指标':'净资产收益率','20260630':12},
            {'指标':'经营活动现金流量净额','20260930':90}]}))
    catalog=industry_catalog(auth.db)
    rows=recommend(auth.db,profile(),catalog)
    assert not next(r for r in rows if r['code']=='600001')['positive_observation']
    data.cached('history:600002:20200101:20261030',3600,'日线隔离测试夹具',lambda:{'items':[{'date':'2026-10-29','close':10}]})
    short=recommend(auth.db,profile(industries=['食品饮料'],period='短期',goal='观察已有走势'),catalog)
    assert short[0]['code']=='600002' and '不预测涨跌' in short[0]['reason']
    data.cached('financial:600002',3600,'财报隔离测试夹具',lambda:{'items':[
        {'指标':'净利润','20260930':20},{'指标':'净资产收益率','20260930':5},
        {'指标':'经营活动现金流量净额','20260930':30}]})
    ordinary=recommend(auth.db,profile(industries=['食品饮料'],period='都看看',goal='了解公司'),catalog)
    steady=recommend(auth.db,profile(industries=['食品饮料'],period='都看看',goal='经营稳健'),catalog)
    assert ordinary[0]['code']=='600001' and steady[0]['code']=='600002'
    data.cached('business:600002',3600,'主营隔离测试夹具',lambda:{'items':[{'主营构成':'夹具产品'}]})
    medium=recommend(auth.db,profile(industries=['食品饮料'],period='中期',goal='了解业务'),catalog)
    assert medium[0]['code']=='600002'



def test_new_user_preferences_home_industry_watch_and_edit_path(system,monkeypatch):
    settings,auth,admin,user=system;seed(auth)
    monkeypatch.setenv('DATABASE_URL',settings.database_url);monkeypatch.setenv('APP_SECRET_KEY',settings.app_secret_key)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.setattr(provider,'call',lambda *a,**k:pytest.fail('No data source calls from product browsing'))
    monkeypatch.setattr(AI,'company_report',lambda *a,**k:pytest.fail('No automatic paid AI calls'))
    app=AppTest.from_file('app.py');app.session_state['token']=user.token;app.run(timeout=20)
    assert len(app.multiselect)==1 and any(x.label=='开始我的研究' for x in app.button)
    app.multiselect[0].set_value(['食品饮料','银行'])
    next(x for x in app.radio if x.label=='研究周期').set_value('长期')
    next(x for x in app.text_input if x.label=='一句话诉求').input(profile()['goal'])
    next(x for x in app.button if x.label=='开始我的研究').click().run(timeout=20)
    saved=user.get('user_preferences','profile')
    assert saved['onboarding_completed'] and saved['period']=='长期' and saved['goal']==profile()['goal']
    assert admin.get('user_preferences','profile') is None
    html='\n'.join(x.proto.body for x in app.get('html'))
    assert '为你推荐' in {x.value for x in app.subheader} and '观察食品甲' in html and '观察银行乙' in html
    assert '尚未核实' in '\n'.join(x.value for x in app.caption)
    app.button(key='rec_watch_600001').click().run(timeout=20)
    assert user.get('watchlist_items','600001')['name']=='观察食品甲（夹具）'
    assert app.button(key='rec_watch_600001').disabled
    assert any(x.key.startswith('home_watch_open') for x in app.button)
    app.radio(key='navigation').set_value('市场').run(timeout=20)
    app.radio(key='market_section').set_value('行业观察').run(timeout=20)
    next(x for x in app.text_input if x.label=='搜索行业').input('银行').run(timeout=20)
    assert app.selectbox[0].options==['银行']
    app.button(key='industry_open_000001').click().run(timeout=20)
    assert app.radio(key='navigation').value=='个股' and app.text_input(key='stock_query').value=='000001'
    app.radio(key='research_tab').set_value('AI研究').run(timeout=20)
    assert any('AI研究服务尚未配置' in x.value for x in app.info)
    assert app.button(key='generate_stock_000001').disabled
    app.radio(key='navigation').set_value('我的').run(timeout=20)
    app.selectbox[0].set_value('个人设置').run(timeout=20)
    next(x for x in app.multiselect if x.label.startswith('关注行业')).set_value(['银行'])
    next(x for x in app.radio if x.label=='研究周期').set_value('中期')
    next(x for x in app.button if x.label=='保存偏好').click().run(timeout=20)
    assert user.get('user_preferences','profile')['period']=='中期'
    assert user.get('user_preferences','profile')['industries']==['银行']
    assert not app.error and not app.exception


def test_prompt_prohibits_unsupported_valuation_math():
    assert '禁止自行年化EPS' in SYSTEM
    assert '禁止自行推导PE/PB、市值或目标价' in SYSTEM
    assert '没有可靠估值数据必须明确缺失' in SYSTEM
    assert VERSION=='company-report-v1.1'

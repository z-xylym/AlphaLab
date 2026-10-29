import json
from datetime import timedelta
import pandas as pd
import pytest
from sqlalchemy import select,update
from alphalab import provider
from alphalab.data import MarketData,DataUnavailable,now
from alphalab.db import cache,public
from alphalab.policy_parser import parse_index

@pytest.mark.parametrize('html',[
 '<div class="entry"><a href="/zhengce/content/202610/content_1.htm" title="测试正式文件标题">标题</a><time datetime="2026-10-28"></time></div>',
 '<li><span>2026年10月28日</span><a href="http://www.gov.cn/zhengce/content/202610/content_1.htm">测试正式文件标题</a></li>',
 '<script type="application/ld+json">{"headline":"测试正式文件标题","url":"/zhengce/content/202610/content_1.htm","datePublished":"2026-10-28T10:00:00+08:00"}</script>',
 '<script>var records = [{"doctitle":"测试正式文件标题","docurl":"/zhengce/content/202610/content_1.htm","docpubtime":"2026.10.28"}];</script>',
])
def test_policy_parser_dated_html_and_embedded_json(html):
    rows,_=parse_index(html)
    assert len(rows)==1 and rows[0]['published_at']=='2026-10-28'
    assert rows[0]['url'].startswith('https://www.gov.cn/')
    assert rows[0]['status']=='待核对原文'


def test_parser_does_not_invent_dates_or_links():
    html='<div><span>2026-10-28</span><a href="/zhengce/content/a.htm">测试甲文件标题</a><a href="/zhengce/content/b.htm">测试乙文件标题</a></div>'
    assert parse_index(html)[0]==[]
    assert parse_index('<a href="/zhengce/content/20261028/a.htm">没有可靠发布日期</a>')[0]==[]
    assert parse_index(json.dumps({'title':'测试文件标题','datePublished':'2026-10-28'}))[0]==[]
    assert parse_index('<li>2026-10-28<a href="https://evil.example/test.htm">测试官方链接拒绝</a></li>')[0]==[]


def test_policy_resources_are_same_origin_and_bounded():
    _,resources=parse_index('<script src="https://evil.example/a.json"></script><iframe src="/zhengce/zuixin/list.htm"></iframe><script src="/jquery.js"></script>')
    assert resources==['https://www.gov.cn/zhengce/zuixin/list.htm']


def test_search_uses_official_master_and_persists_without_prices(system,monkeypatch):
    _,auth,_,_=system
    data=MarketData(auth.db);seen=[]
    def call(name,**kwargs):
        seen.append(name)
        assert name=='security_master_sh'
        return pd.DataFrame([{'证券代码':'600868','证券简称':'梅雁吉祥','上市日期':'1994-09-12'}])
    monkeypatch.setattr(provider,'call',call)
    monkeypatch.setattr(data,'spot',lambda:pytest.fail('Search cannot depend on snapshots'))
    found=data.search('600868')[0]
    assert found['name']=='梅雁吉祥' and found['exchange']=='SH' and found['price'] is None
    assert found['source'] and found['fetched_at'] and not found['stale']
    assert data.company('600868')['items'][0]['上市时间']=='1994-09-12'
    assert seen==['security_master_sh']
    with auth.db.connect() as c:
        row=c.execute(select(public['stock_master']).where(public['stock_master'].c.key=='600868')).mappings().one()
        assert row['payload']['price'] is None


def test_master_exchange_partial_failure_and_name_search(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db)
    def call(name,**kwargs):
        if name=='stock_info_sz_name_code':return pd.DataFrame([{'A股代码':'000001','A股简称':'测试银行','A股上市日期':'1991-04-03'}])
        raise provider.ProviderError('HTTP_FORBIDDEN')
    monkeypatch.setattr(provider,'call',call)
    result=data.search('银行')
    assert len(result)==1 and result[0]['code']=='000001' and result[0]['exchange']=='SZ'


def test_stale_master_returns_immediately_without_request(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db)
    loader=lambda:{'items':[{'code':'600868','name':'梅雁吉祥','exchange':'SH','price':None}]}
    first=data.cached('master:v1:SH',1,'真实源测试夹具',loader,'stock_master')
    with auth.db.begin() as c:c.execute(update(cache).where(cache.c.key=='master:v1:SH').values(expires_at=now()-timedelta(seconds=1)))
    monkeypatch.setattr(provider,'call',lambda *a,**k:pytest.fail('Stale-first must not call upstream'))
    result=data.search('600868')[0]
    assert result['stale'] and result['fetched_at']==first['fetched_at'] and result['price'] is None


def test_sina_daily_preferred_no_eastmoney_first(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db);seen=[]
    def call(name,**kwargs):
        seen.append((name,kwargs))
        assert name=='stock_zh_a_daily' and kwargs['adjust']==''
        return pd.DataFrame([{'date':'2026-10-28','open':10,'high':11,'low':9,'close':10,'volume':100}])
    monkeypatch.setattr(provider,'call',call)
    result=data.history('600868')
    assert len(seen)==1 and result['items'][0]['date']=='2026-10-28' and '新浪' in result['provider']


def test_home_is_cache_only_and_refresh_uses_only_new_sources(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db);calls=[]
    def fail(name,**kwargs):calls.append(name);raise provider.ProviderError('NETWORK_ERROR')
    monkeypatch.setattr(provider,'call',fail)
    for method in (data.spot,data.indices,data.policies,data.sectors):
        with pytest.raises(DataUnavailable):method()
    assert not calls
    with pytest.raises(DataUnavailable):data.indices(refresh=True)
    assert calls==['stock_zh_index_daily']*3


def test_policy_refresh_survives_reload_from_cache(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db)
    def call(name,**kwargs):
        assert name=='government_policy_index'
        return pd.DataFrame([{'title':'官方政策测试夹具','published_at':'2026-10-28','url':'https://www.gov.cn/zhengce/content/a.htm'}])
    monkeypatch.setattr(provider,'call',call)
    fetched=data.policies(refresh=True)
    monkeypatch.setattr(provider,'call',lambda *a,**k:pytest.fail('No upstream on home reload'))
    assert data.policies()['items']==fetched['items']
    assert not data.policies()['stale']


def test_policy_official_redirect_and_json_catalog(monkeypatch):
    import httpx
    from alphalab.data import fetch_policy_index
    original=httpx.Client;seen=[]
    def handler(request):
        seen.append(request.url.host)
        if request.url.path=='/zhengce/zuixin/':return httpx.Response(302,headers={'location':'/zhengce/zuixin/home.htm'})
        if request.url.path.endswith('home.htm'):return httpx.Response(200,text='<script>var file="/zhengce/zuixin/list.json";</script>')
        return httpx.Response(200,json={'data':[{'title':'官方政策测试夹具','url':'/zhengce/content/doc.htm','pubDate':'2026-10-28'}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    result=fetch_policy_index()
    assert result['items'][0]['published_at']=='2026-10-28'
    assert seen==['www.gov.cn']*3


def test_explicit_refresh_failure_keeps_original_cache(system,monkeypatch):
    _,auth,_,_=system;data=MarketData(auth.db)
    original=data.cached('fixture-refresh',1,'fixture-source',lambda:{'items':[{'value':3}]})
    def fail():raise provider.ProviderError('NETWORK_ERROR')
    result=data.cached('fixture-refresh',1,'fixture-source',fail,refresh=True)
    assert result['items']==original['items'] and result['fetched_at']==original['fetched_at'] and result['stale']


def test_indices_publish_only_valid_past_sina_bars(system,monkeypatch):
    from alphalab.db import today
    _,auth,_,_=system;data=MarketData(auth.db)
    def call(name,**kwargs):
        assert name=='stock_zh_index_daily'
        return pd.DataFrame([{'date':str(today()-timedelta(days=2)),'close':100},
            {'date':str(today()-timedelta(days=1)),'close':101},
            {'date':str(today()+timedelta(days=1)),'close':999}])
    monkeypatch.setattr(provider,'call',call)
    result=data.indices(refresh=True)
    assert len(result['items'])==3
    assert all(x['price']==101 and x['change_pct']==pytest.approx(1) for x in result['items'])
    assert {x['name'] for x in result['items']}=={'上证指数','深证成指','创业板指'}


def test_malformed_official_link_does_not_break_valid_rows():
    html='<li>2026-10-28<a href="https://www.gov.cn:invalid/a.htm">无效端口测试文件</a></li><li>2026-10-28<a href="/zhengce/content/a.htm">正确链接测试文件</a></li>'
    rows,_=parse_index(html)
    assert len(rows)==1 and rows[0]['title']=='正确链接测试文件'

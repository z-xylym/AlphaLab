from datetime import date,timedelta
from decimal import Decimal
import pytest
from alphalab.config import UserError
from alphalab.research import screen,position_metrics,observation_returns
from alphalab.trading import paper_order,backtest

def bars(n=160):
    # Explicit synthetic fixtures used ONLY by tests, never production views.
    return [{'date':str(date(2024,1,1)+timedelta(days=i)), 'open':10+i*.01,'close':10.01+i*.01,
        'high':10.1+i*.01,'low':9.9+i*.01,'volume':100000} for i in range(n)]

def test_screen_missing_not_zero_and_filters():
    x={'code':'600001','name':'测试夹具','price':10,'turnover':100000000,'listing_date':'2020-01-01','pe':10,'pb':1}
    assert len(screen([x],'低估值',today=date(2026,1,1)))==1
    for change in [{'name':'*ST夹具'},{'pe':None},{'listing_date':None},{'turnover':0},{'price':None}]:
        assert screen([dict(x,**change)],'低估值')==[]
    assert screen([x],'稳健质量')==[]
    assert len(screen([dict(x,roe=15,profit=100)],'稳健质量'))==1
    assert screen([x],'低估值','创业板')==[]

def test_missing_portfolio_quotes_and_concentration():
    p=[{'code':'600001','quantity':100,'cost':10},{'code':'600002','quantity':100,'cost':10}]
    result,missing=position_metrics(p,{'600001':11})
    assert missing and result[0]['pnl']==100
    assert result[0]['weight_pct'] is None and result[1]['pnl'] is None

def test_t_plus_one_funds_and_duplicate_order(system):
    _,_,_,repo=system
    data=bars(2)
    trade=paper_order(repo,'600001','buy',100,data,'one')
    assert trade['side']=='buy'
    with pytest.raises(UserError,match='已处理'):paper_order(repo,'600001','buy',100,data,'one')
    with pytest.raises(UserError,match='T\\+1'):paper_order(repo,'600001','sell',100,data,'two')
    with pytest.raises(UserError,match='资金不足'):paper_order(repo,'600001','buy',100000,data,'big')
    paper_order(repo,'600001','sell',100,bars(3),'three')
    account=repo.get('portfolios','paper')
    assert not account['lots'] and Decimal(account['cash'])<Decimal('100001')
    with pytest.raises(UserError):paper_order(repo,'300001','buy',100,data,'unsupported')

def test_price_limits_and_no_future_leak():
    data=bars()
    result=backtest(data,'600001')
    assert result['data_hash']==backtest(data,'600001')['data_hash']
    assert result['in_sample']['trades'] and result['out_of_sample']['trades']
    changed=[dict(x) for x in data]
    changed[-1]['close']*=1.02
    assert result['in_sample']==backtest(changed,'600001')['in_sample']
    for segment in ('in_sample','out_of_sample'):
        t=result[segment]['trades'][0]
        bar=next(x for x in data if x['date']==t['date'])
        assert t['price']==pytest.approx(bar['open']*1.001)
    with pytest.raises(UserError):backtest(data[:5],'600001')
    assert result['out_of_sample']['costs']>0

def test_immature_observation_horizons():
    history=bars(7)
    r=observation_returns(history,'2024-01-01',10)
    assert r['1'] is not None and r['5'] is not None and r['20'] is None

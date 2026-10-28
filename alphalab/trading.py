from decimal import Decimal, ROUND_HALF_UP
from datetime import date
import hashlib
import json
import uuid
import numpy as np
import pandas as pd
from .config import UserError
from .db import lock, now

INITIAL_CASH=Decimal('100000')

def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

def fees(notional, side, commission=Decimal('.0003'), stamp=Decimal('.0005')):
    return max(Decimal('5'),notional*commission)+(notional*stamp if side=='sell' else Decimal(0))

def paper_order(repo, code, side, quantity, bars, request_id):
    """Simulation only. Uses latest published daily close, never calls a broker."""
    if side not in ('buy','sell') or quantity<=0 or quantity%100:
        raise UserError('模拟交易仅支持100股整数倍的正数数量。')
    if len(bars)<2:
        raise UserError('至少需要两个有效交易日用于检查价格限制。')
    latest,previous=bars[-1],bars[-2]
    close=Decimal(str(latest['close'])); prev=Decimal(str(previous['close']))
    if latest.get('volume',0)<=0 or close<=0 or prev<=0:
        raise UserError('停牌或价格无效，不能模拟成交。')
    # Conservative: do not attempt unimplemented ST/new-listing/Beijing price rules.
    if not code.startswith(('600','601','603','605','000','001','002','003')):
        raise UserError('模拟撮合目前仅支持非ST沪深主板；其他板块待验证。')
    if abs(close/prev-1)>=Decimal('.095'):
        raise UserError('接近涨跌停，模拟器保守拒绝成交。')
    day=str(latest['date'])[:10]
    # Historical close matching is an educational ledger, not a live executable quote.
    with repo.db.begin() as c:
        user=repo.auth.principal(c,repo.token)
        lock(c,'paper:'+str(user['id']))
        if repo._list(c,'simulated_trades',request_id):
            raise UserError('此订单已处理，不会重复成交。')
        account_rows=repo._list(c,'portfolios','paper')
        account=account_rows[0]['payload'] if account_rows else {'cash':str(INITIAL_CASH),'lots':[]}
        cash=Decimal(account['cash']);lots=account['lots']
        if lots and day<max(x['date'] for x in lots):
            raise UserError('行情早于账本时间，拒绝使用过时价格。')
        available=sum(x['quantity'] for x in lots if x['code']==code and x['date']<day)
        price=close*(Decimal('1.001') if side=='buy' else Decimal('.999'))
        notional=money(price*quantity); cost=money(fees(notional,side))
        if side=='buy':
            if cash<notional+cost:
                raise UserError('模拟资金不足。')
            cash-=notional+cost
            lots.append({'code':code,'quantity':quantity,'date':day,'price':str(price)})
        else:
            if available<quantity:
                raise UserError('可卖数量不足；A股T+1不允许卖出当日买入股票。')
            left=quantity
            for lot in lots:
                if lot['code']==code and lot['date']<day:
                    taken=min(left,lot['quantity']);lot['quantity']-=taken;left-=taken
            lots=[x for x in lots if x['quantity']>0]
            cash+=notional-cost
        trade={'code':code,'side':side,'quantity':quantity,'price':str(price),'fees':str(cost),
               'data_date':day,'created_at':now().isoformat(),'mode':'最近日线收盘价记账，非实时撮合'}
        repo._put(c,'portfolios','paper',{'cash':str(cash),'lots':lots})
        repo._put(c,'simulated_trades',request_id,trade)
        return trade

BACKTEST_VERSION='sma-next-open-v1'

def backtest(bars, code, fast=5, slow=20, split=.7, commission=.0003, stamp=.0005, slippage=.001):
    if not 2<=fast<slow<=250 or not .2<=split<=.9:
        raise UserError('均线参数或样本划分无效。')
    if not code.startswith(('600','601','603','605','000','001','002','003')):
        raise UserError('实验回测仅支持已核实非ST沪深主板股票。')
    df=pd.DataFrame(bars).sort_values('date').reset_index(drop=True)
    required={'date','open','high','low','close','volume'}
    if not required.issubset(df.columns) or len(df)<slow+10:
        raise UserError('历史数据不足。')
    if df['date'].duplicated().any() or df[list(required-{'date'})].isna().any().any():
        raise UserError('历史日线存在重复日期或缺失字段。')
    for col in required-{'date'}:
        df[col]=pd.to_numeric(df[col],errors='raise')
    if (df[['open','high','low','close']]<=0).any().any() or (df['high']<df['low']).any() or (df['volume']<0).any():
        raise UserError('历史价格无效。')
    df['signal']=(df.close.rolling(fast).mean()>df.close.rolling(slow).mean()).astype(int)
    cut=int(len(df)*split)
    def run(start,end):
        cash=100000.;qty=0;bought=-1;equity=[];trades=[];costs=0
        for i in range(start,end):
            row=df.iloc[i]; prev=df.iloc[i-1]
            # Signals observed at yesterday close, execution today open. Never use current close for signal.
            desired=int(prev['signal']);price=float(row['open'])
            # Static non-ST main-board rules only; reject large corporate-action discontinuities.
            locked=(price/float(prev.close)>=1.095 or price/float(prev.close)<=.905 or row.volume<=0)
            if not locked and desired and not qty:
                buy=price*(1+slippage)
                size=int((cash-5)/(buy*(1+commission))/100)*100
                if size>0:
                    fee=max(5,size*buy*commission);cash-=size*buy+fee;qty=size;bought=i;costs+=fee+size*(buy-price)
                    trades.append({'date':str(row.date),'side':'buy','price':buy,'quantity':size,'fees':fee})
            elif not locked and not desired and qty and bought<i:
                sell=price*(1-slippage);fee=max(5,qty*sell*commission)+qty*sell*stamp
                cash+=qty*sell-fee;costs+=fee+qty*(price-sell)
                trades.append({'date':str(row.date),'side':'sell','price':sell,'quantity':qty,'fees':fee});qty=0
            equity.append({'date':str(row.date),'equity':cash+qty*float(row.close)})
        curve=pd.Series([x['equity'] for x in equity])
        return {'return_pct':(curve.iloc[-1]/100000-1)*100,
                'max_drawdown_pct':float(((curve/curve.cummax())-1).min()*100),
                'benchmark_pct':(float(df.iloc[end-1].close)/float(df.iloc[start].open)-1)*100,
                'costs':costs,'trades':trades,'curve':equity,'open_quantity':qty,
                'forward_returns_pct':{str(n):None if len(curve)<n else (float(curve.iloc[n-1])/100000-1)*100 for n in (1,5,20)}}
    if cut<=slow or len(df)-cut<5:
        raise UserError('样本内外有效数据不足，请扩大日期范围。')
    params={'version':BACKTEST_VERSION,'code':code,'fast':fast,'slow':slow,'split':split,
            'commission':commission,'stamp':stamp,'slippage':slippage}
    digest=hashlib.sha256(json.dumps({'bars':bars,'params':params},sort_keys=True,default=str).encode()).hexdigest()
    return {'params':params,'data_hash':digest,'in_sample':run(slow,cut),'out_of_sample':run(cut,len(df)),
       'warning':'实验性质：仅价格均线、历史固定10%限制与固定税率；未建模历史ST变更、新股、复权和分红，存在幸存者偏差。不能视为可实现收益。样本外独立从现金开始。'}

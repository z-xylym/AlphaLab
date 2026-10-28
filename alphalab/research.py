from dataclasses import dataclass
from datetime import date, datetime
import pandas as pd
from .data import number
from .db import today as local_today

@dataclass(frozen=True)
class ScreenRules:
    min_listing_days: int = 365
    min_turnover: float = 50_000_000
    min_roe: float = 10
    min_profit: float = 0
    max_pe: float = 25
    max_pb: float = 3
    min_momentum_pct: float = 1
    max_momentum_pct: float = 7
    max_results: int = 5

RULES=ScreenRules()

def screen(items, strategy, board='全部A股', rules=RULES, today=None):
    today=today or local_today()
    results=[]
    for raw in items:
        x=dict(raw)
        code=str(x.get('code',''))
        name=str(x.get('name',''))
        if not code.isdigit() or len(code)!=6 or any(t in name.upper() for t in ('ST','退')):
            continue
        if board=='沪深主板' and not code.startswith(('600','601','603','605','000','001','002','003')):
            continue
        if board=='创业板' and not code.startswith(('300','301')):
            continue
        if board=='科创板' and not code.startswith(('688','689')):
            continue
        listed=pd.to_datetime(x.get('listing_date'),errors='coerce')
        turnover=number(x.get('turnover'))
        price=number(x.get('price'))
        if pd.isna(listed) or (today-listed.date()).days<rules.min_listing_days or turnover is None or turnover<rules.min_turnover or price is None or price<=0:
            continue
        if strategy=='低估值':
            pe,pb=number(x.get('pe')),number(x.get('pb'))
            if pe is None or pb is None or not (0<pe<=rules.max_pe and 0<pb<=rules.max_pb):
                continue
            reason=f'动态PE≤{rules.max_pe}、PB≤{rules.max_pb}，不代表内在价值已确认'
        elif strategy=='稳健质量':
            roe,profit=number(x.get('roe')),number(x.get('profit'))
            if roe is None or profit is None or roe<rules.min_roe or profit<=rules.min_profit:
                continue
            reason=f'已提供ROE≥{rules.min_roe}%、净利润为正；需继续核对现金流'
        elif strategy=='趋势动量':
            change=number(x.get('change_pct'))
            if change is None or not rules.min_momentum_pct<=change<=rules.max_momentum_pct:
                continue
            reason='单日涨幅落在配置区间；仅为实验性短期动量观察'
        else:
            continue
        x.update(reason=reason,strategy=strategy,risk='估值陷阱、业绩变化、流动性与市场波动均可能导致损失。')
        results.append(x)
    return sorted(results,key=lambda x:x['code'])[:rules.max_results]

def position_metrics(positions, quotes):
    rows=[]
    total=0
    for p in positions:
        price=number(quotes.get(p['code']))
        qty=float(p['quantity']); cost=float(p['cost'])
        value=price*qty if price is not None else None
        if value is not None:
            total+=value
        rows.append({**p,'market_value':value,'pnl':None if value is None else value-cost*qty,
                     'return_pct':None if price is None or cost<=0 else (price/cost-1)*100})
    incomplete=any(x['market_value'] is None for x in rows)
    for x in rows:
        x['weight_pct']=None if incomplete or not total or x['market_value'] is None else x['market_value']/total*100
    return rows,incomplete

def observation_returns(history, saved_date, reference_price):
    """Forward observations use bars strictly AFTER saved day; no invented immature returns."""
    frame=pd.DataFrame(history)
    frame['date']=pd.to_datetime(frame['date'])
    future=frame[frame['date'].dt.date>date.fromisoformat(saved_date[:10])].sort_values('date')
    return {str(n): None if len(future)<n else (float(future.iloc[n-1]['close'])/reference_price-1)*100 for n in (1,5,20)}

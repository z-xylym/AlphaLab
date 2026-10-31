"""Explainable cache-only discovery. No AI classification, price predictions or network calls."""
import re
from collections import defaultdict
from sqlalchemy import select, or_, func
from .db import cache
from .data import MarketData, DataUnavailable

PERIODS = ('短期', '中期', '长期', '都看看')
INTERESTS = ('食品饮料', '银行', '医药生物', '电子', '计算机', '机械设备', '公用事业', '汽车', '电力设备', '基础化工', '交通运输')
UNKNOWN = {'', '暂无可靠数据', '未知', '不详', 'nan', 'None', '—'}


def data_version(db, prefixes):
    """Payload-free cache version; include expiration transitions and deletions."""
    from .db import now
    condition = or_(*(cache.c.key.startswith(prefix) for prefix in prefixes))
    with db.connect() as conn:
        row = conn.execute(select(func.count(), func.max(cache.c.fetched_at),
            func.max(cache.c.expires_at), func.count().filter(cache.c.expires_at <= now())).where(condition)).first()
    return tuple(str(value) for value in row)


def industry_catalog(db):
    """Union explicit company classifications and saved industry memberships; never infer a label."""
    stocks = {};groups = defaultdict(set);sources = {}
    try:master = MarketData(db).security_master(cached_only=True)['items']
    except DataUnavailable:master = []
    def valid(row):return isinstance(row.get('code'),str) and re.fullmatch(r'\d{6}', row['code']) and row.get('name') and row.get('source')
    def add_group(name, code, metadata):
        name = str(name or '').strip()
        if name not in UNKNOWN and len(name) <= 100:
            groups[name].add(code) if code else groups[name]
            sources.setdefault(name, metadata)
    for row in master:
        if not valid(row):continue
        stocks[row['code']] = dict(row)
        add_group(row.get('industry'), row['code'], {k: row.get(k) for k in ('source', 'fetched_at', 'stale')})
    with db.connect() as conn:
        rows = conn.execute(select(cache).where((cache.c.key == 'sectors:False') | cache.c.key.startswith('members:False:') | (cache.c.key == 'spot:v1'))).mappings().all()
    quotes = {};quote_meta = None
    from .db import now
    for saved in rows:
        if not saved['source']:continue
        metadata = {'source': saved['source'], 'fetched_at': saved['fetched_at'].isoformat(), 'stale': saved['expires_at'] <= now()}
        if saved['key'] == 'spot:v1':
            quotes = {r['code']: r for r in saved['payload'].get('items', []) if r.get('code')}
            quote_meta = metadata
        elif saved['key'] == 'sectors:False':
            for row in saved['payload'].get('items', []):add_group(row.get('name'), None, metadata)
        else:
            name = saved['key'][len('members:False:'):]
            for row in saved['payload'].get('items', []):
                entry = dict(row, **metadata)
                if not valid(entry):continue
                stocks.setdefault(row['code'], entry)
                add_group(name, row['code'], metadata)
    return {'stocks': stocks, 'industries': {name: sorted(codes) for name, codes in sorted(groups.items())},
            'industry_sources': sources, 'quotes': quotes, 'quote_metadata': quote_meta}


def recommend(db, profile, catalog, limit=6):
    """Preference match -> observable evidence readiness -> code, with industry round-robin diversity."""
    if not profile.get('onboarding_completed'):return []
    requested = profile.get('industries', [])
    available = catalog['industries']
    selected = [name for name in requested if name in available] if requested else list(available)
    codes = sorted({code for name in selected for code in available[name]})
    # Bounded input enrichment, not a claim of full-market coverage. One bulk cache query.
    candidates = codes[:60]
    if not candidates:return []
    with db.connect() as conn:
        rows = conn.execute(select(cache).where(cache.c.key.in_(['financial:'+code for code in candidates]+['business:'+code for code in candidates])).order_by(cache.c.fetched_at.desc())).mappings()
        financial = {};financial_meta = {};business = set();history = set()
        for row in rows:
            parts = row['key'].split(':');code = parts[1] if len(parts) > 1 else ''
            if code not in candidates or not row['source']:continue
            if parts[0] == 'financial':
                financial.setdefault(code, MarketData.financial_summary(row['payload']))
                from .db import now
                financial_meta.setdefault(code,{'source':row['source'],'fetched_at':row['fetched_at'].isoformat(),'stale':row['expires_at']<=now()})
            elif parts[0] == 'business' and row['payload'].get('items'):business.add(code)
        history_keys=conn.execute(select(cache.c.key).where(or_(*(cache.c.key.startswith('history:'+code+':') for code in candidates)))).scalars()
        history.update(key.split(':')[1] for key in history_keys)
    goal = profile.get('goal', '')
    steady = any(word in goal for word in ('稳健', '稳定', '现金流', '风险'))
    period = profile.get('period', '都看看')
    by_industry = defaultdict(list)
    for code in candidates:
        stock = catalog['stocks'][code]
        matched = [name for name in selected if code in available[name]]
        metrics = financial.get(code, {})
        required = [metrics.get(name, {}) for name in ('净利润', 'ROE', '经营现金流')]
        complete = all(r.get('value') is not None and r.get('report_date') for r in required)
        aligned = complete and len({r['report_date'] for r in required}) == 1
        positive = aligned and all(r['value'] > 0 for r in required)
        if steady or period == '长期':tier = 0 if positive else 1 if complete else 2
        elif period == '中期':tier = 0 if code in business and any(r.get('value') is not None for r in metrics.values()) else 1
        elif period == '短期':tier = 0 if code in history else 1
        else:tier = 0
        reason = '符合你关注的“'+'、'.join(matched)+'”方向。' if requested else '你未限定行业，来自已有明确行业归属的公司。'
        if steady:reason += '你提到稳健或风险，优先核对盈利、ROE和经营现金流。'
        if period == '长期':reason += '长期观察优先看财务资料，非股价预测。'
        elif period == '中期':reason += '中期观察优先看是否已有主营与可用财务摘要，不代表指标全部齐全。'
        elif period == '短期':reason += '短期观察优先看是否已有历史走势资料，不预测涨跌。'
        if positive:reason += '已有同报告期的净利润、ROE和经营现金流为正。'
        risk = '单期财务为正不代表经营长期稳定；实时估值缺失。' if positive else '财务不齐、报告期不一致或部分指标非正，经营稳健性尚未核实。'
        if stock.get('stale'):risk += '证券资料为历史记录，请核对日期。'
        item = {'code': code, 'name': stock['name'], 'industry': ' / '.join(matched), 'reason': reason, 'risk': risk,
                'source': stock['source'], 'fetched_at': stock.get('fetched_at'), 'stale': stock.get('stale', False),
                'period': period, 'positive_observation': bool(positive), 'financial_metadata': financial_meta.get(code), 'financial_period': required[0].get('report_date') if aligned else None,
                'quote': catalog['quotes'].get(code, {}), 'quote_metadata': catalog['quote_metadata']}
        for name in matched:by_industry[name].append((tier, code, item))
    for rows in by_industry.values():rows.sort(key=lambda row: (row[0], row[1]))
    result = [];seen = set()
    while len(result) < limit:
        added = False
        for name in selected:
            rows = by_industry[name]
            while rows and rows[0][1] in seen:rows.pop(0)
            if rows:
                _, code, item = rows.pop(0);result.append(item);seen.add(code);added = True
            if len(result) >= limit:break
        if not added:break
    return result

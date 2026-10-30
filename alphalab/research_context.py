"""Bounded, cache-only company evidence. No network calls, private memory or credentials."""
import hashlib
import json
import re
from .data import MarketData, number, financial_label

VERSION = 'company-context-v1'
MISSING = (None, '', '暂无可靠数据', 'nan', 'None', '—')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(context):
    # A re-fetch of identical facts is not a substantive context change. Staleness IS evidence.
    def stable(value):
        if isinstance(value, dict):return {k: stable(v) for k, v in value.items() if k != 'fetched_at'}
        if isinstance(value, list):return [stable(v) for v in value]
        return value
    return hashlib.sha256(canonical(stable(context)).encode()).hexdigest()


def build_context(stock, company=None, financial=None, history=None, business=None, policies=None):
    missing = []
    sources = {}
    dates = []
    def text(value):
        return str(value)[:500] if value not in MISSING and str(value).strip().lower() not in ('nan','none','null') else None
    def item(path, value, data, date=None, unit=None):
        absent = value is None or value == []
        if absent:missing.append(path)
        source = str((data or {}).get('source') or '来源未提供')[:300]
        fetched = (data or {}).get('fetched_at')
        if date and re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}', str(date)):
            date = str(date)
            date = date if '-' in date else date[:4]+'-'+date[4:6]+'-'+date[6:]
            dates.append(date)
        else:date = None
        sources[path] = {'source': source, 'fetched_at': fetched, 'stale': bool((data or {}).get('stale')), 'date': date}
        return {'value': value, 'date': date, 'source': source, 'fetched_at': fetched,
                'missing': absent, 'cached': bool(data), 'stale': bool((data or {}).get('stale')), 'unit': unit}
    profile = (company or {}).get('items', [{}])[0] if (company or {}).get('items') else {}
    security = {k: item('security.'+k, text(stock.get(k)), stock) for k in ('code', 'name', 'exchange')}
    company_profile = {k: item('company_profile.'+k, text(profile.get(label)), company,
                             profile.get(label) if k == 'listing_date' else None)
                       for k, label in (('listing_date', '上市时间'), ('industry', '行业'), ('total_shares', '总股本'))}
    summary = MarketData.financial_summary(financial or {'items': []})
    aliases = {
        '营业收入': ('营业总收入', '营业收入'),
        '净利润': ('归母净利润', '归属母公司股东的净利润', '归属于母公司股东的净利润', '净利润'),
        'ROE': ('净资产收益率(ROE)', '净资产收益率', '加权净资产收益率', '加权平均净资产收益率', '净资产收益率(加权)', '净资产收益率(加权平均)', '净资产收益率-加权'),
        '毛利率': ('销售毛利率', '毛利率'), '资产负债率': ('资产负债率',),
        '经营现金流': ('经营活动产生的现金流量净额', '经营活动现金流量净额')}
    financial_summary = {}
    for name, row in summary.items():
        original = next((str(r.get('指标')) for r in reversed((financial or {}).get('items', []))
                         if financial_label(r.get('指标', '')) in aliases[name]), None)
        unit = '%' if original and ('%' in original or '％' in original) else ('元' if original and financial_label(original) != original and '元' in original else '源未标注单位，不换算')
        financial_summary[name] = dict(item('financial_summary.'+name, row['value'], financial,
                                            row['report_date'], unit), original_indicator=original)
    bars = []
    for row in (history or {}).get('items', []):
        date = str(row.get('date', ''))[:10]
        close = number(row.get('close'))
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) and close is not None and close > 0:
            bars.append({'date': date, 'close': close})
    bars = sorted({r['date']: r for r in bars}.values(), key=lambda r: r['date'])[-60:]
    price = None
    if bars:
        price = {'first_date': bars[0]['date'], 'last_date': bars[-1]['date'], 'observations': len(bars),
                 'first_close': bars[0]['close'], 'last_close': bars[-1]['close'],
                 'min_close': min(r['close'] for r in bars), 'max_close': max(r['close'] for r in bars),
                 'recent_closes': bars[-10:], 'basis': '最多60个已有交易日的不复权收盘价；不是实时价格，不保证未来表现'}
    history_summary = item('price_history_summary', price, history, bars[-1]['date'] if bars else None, '元/股，不复权')
    composition = []
    for row in (business or {}).get('items', [])[:15]:
        composition.append({k: text(row.get(k)) for k in ('主营构成', '分类类型', '主营收入', '收入比例', '主营利润', '报告日期')})
    composition.sort(key=canonical)
    business_dates = [r['报告日期'][:10] for r in composition if r.get('报告日期')]
    business_summary = item('business_composition', composition or None, business, max(business_dates, default=None))
    business_summary['coverage'] = {'included_rows': len(composition), 'cached_rows': len((business or {}).get('items', [])), 'limit': 15}
    # Policy index records are general observations, never verified company relevance or full policy measures.
    policy_rows = []
    for row in (policies or {}).get('items', []):
        url = str(row.get('url', ''))
        if not url.startswith('https://www.gov.cn/') or not row.get('published_at'):continue
        policy_rows.append({k: text(row.get(k)) for k in ('title', 'url', 'published_at', 'publisher', 'status')})
    policy_rows = sorted(policy_rows, key=lambda r: (r['published_at'], r['url']), reverse=True)[:5]
    policy_summary = item('policy_context', policy_rows or None, policies,
                          max((r['published_at'] for r in policy_rows), default=None))
    policy_summary['coverage'] = {'included_rows': len(policy_rows), 'cached_rows': len((policies or {}).get('items', [])), 'limit': 5, 'company_relevance_verified': False}
    for name in ('实时价格', 'PE', 'PB'):missing.append(name)
    return {'schema_version': VERSION, 'security': security, 'company_profile': company_profile,
            'financial_summary': financial_summary, 'price_history_summary': history_summary,
            'business_composition': business_summary, 'policy_context': policy_summary,
            'policy_scope': '仅官方索引；未验证与公司的相关性，未提供政策全文，不可声称公司直接受益',
            'missing_data': sorted(missing), 'source_metadata': sources,
            'data_cutoff': max(dates, default=None), 'cutoff_note': '各资料日期的最大值，不表示全部数据更新至同一天；逐项核对日期'}


def context_from_cache(view, stock):
    def read(loader):
        try:return loader()
        except Exception:return None
    code = stock['code']
    return build_context(stock, read(lambda: view.company(code)), read(lambda: view.financials(code)),
                         read(lambda: view.history(code)), read(lambda: view.business(code)), read(view.policies))

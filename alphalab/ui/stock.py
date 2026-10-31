from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import plotly.express as px
import streamlit as st
from ..data import DataUnavailable, number
from ..research_context import build_context
from .components import data_meta, date_label, empty_state, fmt, metric_grid, chart_style, planned_panel, financial_value, financial_tone
from .reads import CachedResearch, invalidate, remember

GLOSSARY = {
    '营业收入': '产品或服务收入，不等于利润。', '净利润': '扣除成本费用后的利润。',
    'ROE': '净资产收益率；需结合杠杆与行业判断。', '毛利率': '收入扣除直接成本后的比例。',
    '资产负债率': '负债占资产的比例。', '经营现金流': '经营活动实际现金净流入。',
}


def optional(loader):
    try:
        return loader()
    except Exception:
        return None


def field(value):
    return '—' if value is None or str(value) in ('', '暂无可靠数据', 'nan', 'None') else str(value)


def financial_metrics(view, financial, compact=False):
    if not financial:
        empty_state('财务数据待更新', '通过当前页的独立获取入口取得最新披露。')
        return
    data_meta(financial)
    summary = build_context({'code': '', 'name': ''}, financial=financial)['financial_summary']
    metrics = []
    for name, item in list(summary.items())[:3 if compact else 6]:
        label = item.get('original_indicator') or name
        metrics.append((label, financial_value(name, item['value'], label),
                        '报表期 '+field(item['date']), financial_tone(name, item['value'])))
    metric_grid(metrics)
    if not compact:
        with st.expander('指标口径与原始摘要'):
            for name, description in GLOSSARY.items():
                st.caption(name+' · '+description)
            st.caption('单位以原始指标名称为准；报表期不等于公告日，不用于历史财务选股回测。')
            st.dataframe(pd.DataFrame(financial['items']), hide_index=True, use_container_width=True)


def fetch_independent(view, data, code, method, label, existing=None):
    current = existing or optional(lambda: getattr(view, method)(code))
    failed_key = '_fetch_failed_'+method+'_'+code
    caption = ('重试获取' if st.session_state.get(failed_key) else '获取')+label
    if not current or not current.get('items'):
        if st.button(caption, key='fetch_'+method+'_'+code):
            try:
                with st.spinner('正在获取'+label+'…'):
                    current = getattr(data, method)(code, refresh=True)
                invalidate()
                if not current or not current.get('items'):raise DataUnavailable('empty')
                st.session_state.pop(failed_key, None)
            except Exception:
                st.session_state[failed_key] = True
                st.warning(label+'暂不可用，可单独重试；其他资料不受影响。')
                return None
    return current if current and current.get('items') else None


def stock_research(data, repo, ai, level):
    view = CachedResearch(data.db)
    title = st.empty()
    with st.container(key='search_bar'):
        with st.form('stock_search', border=False):
            search, submit = st.columns([5, 1], vertical_alignment='bottom')
            with search:
                query = st.text_input('股票名称或代码', placeholder='贵州茅台 / 600519', key='stock_query')
            with submit:
                submitted = st.form_submit_button('搜索', type='primary')
    if submitted:
        st.session_state['research_query'] = query.strip()
    query = st.session_state.get('research_query', '')
    if not query:
        title.header('个股研究')
        empty_state('选择一家值得研究的公司', '输入股票名称或六位代码。')
        return
    try:
        matches = view.search(query)
    except DataUnavailable:
        empty_state('基础名单待更新', '请联系管理员更新证券名单。')
        return
    if not matches:
        empty_state('未找到匹配股票', '试试完整代码或其他关键词。')
        return
    lookup = {f"{x['name']} · {x['code']}": x for x in matches}
    if len(lookup) > 1:
        choice = st.selectbox('搜索结果', list(lookup))
        stock = lookup[choice]
    else:
        stock = matches[0]
    code = stock['code']
    with st.container(key='company_header'):
        header, action = st.columns([4, 1], vertical_alignment='center')
        with header:
            st.header(stock['name'])
            st.caption(f"{code} · {stock.get('exchange', '—')}")
        with action:
            if st.button('加入自选', key='watch_'+code):
                repo.put('watchlist_items', code, {'code': code, 'name': stock['name']})
                st.success('已加入自选')
    has_report = repo.has_company_report(code)
    st.caption('研究状态 · '+('已有历史AI研究，可在AI研究页签核对' if has_report else '待形成公司研究'))
    data_meta(stock, price_missing=number(stock.get('price')) is None)
    if number(stock.get('price')) is not None:
        st.caption('最新可用价格 '+fmt(stock['price'], ' 元'))
    if st.button('更新研究数据', type='primary', key='refresh_research'):
        loaders = [lambda: data.history(code, refresh=True), lambda: data.financials(code, refresh=True),
                   lambda: data.business(code, refresh=True)]
        def update(loader):
            try:
                result = loader()
                return not result.get('stale')
            except Exception:
                return False
        with st.spinner('正在更新研究数据…'):
            with ThreadPoolExecutor(max_workers=3) as executor:
                successes = list(executor.map(update, loaders))
        invalidate()
        if all(successes):
            st.success('研究数据已更新')
        elif any(successes):
            st.caption('部分数据已更新，其余保留已有记录。')
        else:
            st.caption('暂未取得新数据，保留已有记录。')

    # Radio tabs execute only the selected body. The header needs no report bodies or day bars.
    with st.container(key='research_tabs'):
        tab = st.radio('研究内容', ['概览', '走势', '财务', '主营', 'AI研究', '预警'], horizontal=True,
                       key='research_tab', label_visibility='collapsed')
    financial = optional(lambda: view.financials(code)) if tab in ('概览', '财务') else None
    if tab == '概览':
        quote_data = optional(lambda: remember('watch_quotes', view.spot))
        quote = next((x for x in quote_data['items'] if x['code'] == code), {}) if quote_data else {}
        change = number(quote.get('change_pct'))
        core = [('已有价格', fmt(quote.get('price'), ' 元'), '非实时 · 缺失不影响研究', ''),
                ('涨跌幅', fmt(change, '%'), '已有行情快照',
                 'up' if change is not None and change > 0 else 'down' if change is not None and change < 0 else 'neutral')]
        contextual = build_context(stock, financial=financial)['financial_summary']
        for name, item in contextual.items():
            core.append((name, financial_value(name, item['value'], item.get('original_indicator')),
                         '报表期 '+field(item['date']), financial_tone(name, item['value'])))
        with st.container(key='core_metrics'):metric_grid(core, columns=4)

    if tab == '概览':
        info = optional(lambda: view.company(code))
        company = info['items'][0] if info else {}
        latest = max((str(x.get('date') or '') for x in contextual.values()), default='—')
        metric_grid([(label, field(value), '', '') for label, value in (
            ('上市时间', date_label(company.get('上市时间'))), ('所属行业', company.get('行业')),
            ('总股本', company.get('总股本')), ('最新数据日期', latest))], columns=4)
        with st.expander('资料来源与研究口径'):
            st.caption('顶部指标只读已有缓存，财务报告期与价格日期分别标注。完整财务请查看财务页签。')
            data_meta(info)
            data_meta(financial)
    elif tab == '走势':
        history = fetch_independent(view, data, code, 'history', '走势')
        if not history:return
        data_meta(history)
        def chart_frame():
            frame = pd.DataFrame(history['items'])
            frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
            frame = frame.dropna(subset=['date']).sort_values('date')
            return frame[frame['date'] >= frame['date'].max()-pd.DateOffset(years=3)]
        frame = remember(('chart', code, history['fetched_at']), chart_frame)
        st.plotly_chart(chart_style(px.line(frame, x='date', y='close',
                                           labels={'date': '日期', 'close': '不复权收盘价（元）'})),
                        use_container_width=True, config={'displayModeBar': False})
        st.caption('不复权日线 · 最新数据日期 '+max(str(x['date']) for x in history['items']))
        with st.expander('数据口径与回测风险'):
            st.caption('未复权价格受分红送转影响，不代表实际投资回报；历史走势不预测未来。')
    elif tab == '财务':
        financial = fetch_independent(view, data, code, 'financials', '财务', existing=financial)
        financial_metrics(view, financial)
    elif tab == '主营':
        business = fetch_independent(view, data, code, 'business', '主营')
        if not business:
            empty_state('主营数据待更新', '通过当前页的独立获取入口取得最新披露。')
            return
        data_meta(business)
        frame = pd.DataFrame(business['items'])
        fields = [k for k in ('主营构成', '分类类型', '主营收入', '收入比例', '主营利润', '报告日期') if k in frame]
        st.dataframe(frame[fields] if fields else frame, hide_index=True, use_container_width=True)
        st.caption('按披露报告期展示；不同分类口径不可叠加。')
    elif tab == '预警':
        st.subheader('预警与跟踪')
        planned_panel('条件触发与风险提示', '规划中；当前未监测或发送通知，也未创建任何价格或财务阈值。')
        with st.expander('研究期限与观察框架'):
            for horizon in ('短期观察','中期经营','长期价值'):
                planned_panel(horizon, '规划中；后续将记录关注指标与判断失效条件，当前不生成期限观点。')
    else:
        from .company_ai import company_ai
        company_ai(view, stock, ai)

from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import plotly.express as px
import streamlit as st
from ..data import DataUnavailable, number
from .components import data_meta, date_label, empty_state, fmt, metric_grid, ai_button, chart_style
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
        empty_state('财务数据待更新', '点击“更新研究数据”取得最新披露。')
        return
    data_meta(financial)
    summary = view.financial_summary(financial)
    metrics = []
    for name, item in list(summary.items())[:3 if compact else 6]:
        unit = ' %' if name in ('ROE', '毛利率', '资产负债率') else ''
        # Monetary units vary by source label. Do not infer a unit from magnitude.
        label = next((str(row.get('指标')) for row in financial['items']
                      if str(row.get('指标', '')).startswith(name)), name)
        metrics.append((label, fmt(item['value'], unit),
                        '报表期 '+field(item['report_date']), ''))
    metric_grid(metrics)
    if not compact:
        with st.expander('指标口径与原始摘要'):
            for name, description in GLOSSARY.items():
                st.caption(name+' · '+description)
            st.caption('单位以原始指标名称为准；报表期不等于公告日，不用于历史财务选股回测。')
            st.dataframe(pd.DataFrame(financial['items']), hide_index=True, use_container_width=True)


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

    # A native radio styled as tabs provides true conditional execution in Streamlit 1.50.
    with st.container(key='research_tabs'):
        tab = st.radio('研究内容', ['概览', '走势', '财务', '主营', 'AI研究'], horizontal=True,
                       key='research_tab', label_visibility='collapsed')
    if tab == '概览':
        info = optional(lambda: view.company(code))
        company = info['items'][0] if info else {}
        history = optional(lambda: view.history(code))
        latest = max((str(x['date']) for x in history['items']), default='—') if history else '—'
        metric_grid([(label, field(value), '', '') for label, value in (
            ('上市时间', date_label(company.get('上市时间'))), ('所属行业', company.get('行业')),
            ('总股本', company.get('总股本')), ('最新数据日期', latest))], columns=4)
        st.subheader('核心财务')
        financial = optional(lambda: view.financials(code))
        financial_metrics(view, financial, compact=True)
    elif tab == '走势':
        history = optional(lambda: view.history(code))
        if not history:
            empty_state('日线数据待更新', '点击“更新研究数据”后查看走势。')
            return
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
        financial_metrics(view, optional(lambda: view.financials(code)))
    elif tab == '主营':
        business = optional(lambda: view.business(code))
        if not business:
            empty_state('主营数据待更新', '点击“更新研究数据”取得最新披露。')
            return
        data_meta(business)
        frame = pd.DataFrame(business['items'])
        fields = [k for k in ('主营构成', '分类类型', '主营收入', '收入比例', '主营利润', '报告日期') if k in frame]
        st.dataframe(frame[fields] if fields else frame, hide_index=True, use_container_width=True)
        st.caption('按披露报告期展示；不同分类口径不可叠加。')
    else:
        st.subheader('公司研究')
        st.caption('基于当前已取得的公司、财务、主营与历史数据。')
        info = optional(lambda: view.company(code))
        financial = optional(lambda: view.financials(code))
        business = optional(lambda: view.business(code))
        history = optional(lambda: view.history(code))
        evidence = {'stock': stock, 'company': info, 'business': business,
                    'financials': view.compact_financials(financial) if financial else None,
                    'latest_bars': dict(history, items=history['items'][-20:]) if history else None}
        with st.expander('本次研究资料'):
            for title, value in (('基础资料', info), ('财务', financial), ('主营', business), ('日线', history)):
                st.caption(title+(' · 已取得' if value else ' · 尚未取得'))
                data_meta(value)
        ai_button(ai, 'stock', '生成研究报告', evidence, stock['name']+' '+code, level, key='stock_'+code)

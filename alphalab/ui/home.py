import streamlit as st
from ..data import read_home_sections, number
from .components import data_meta, date_label, empty_state, fmt, metric_grid, ai_button
from .reads import remember, invalidate


def policy_cards(items):
    for policy in items[:3]:
        st.caption(f"{date_label(policy.get('published_at'))} · {policy.get('publisher', '中国政府网')}")
        with st.expander(policy['title']):
            st.caption('政策索引 · 具体内容与生效状态以原文为准')
            if policy.get('content'):
                st.write(policy['content'])
            st.link_button('阅读官方原文', policy['url'])


def home(data, repo, ai, level):
    heading, action = st.columns([4, 1], vertical_alignment='center')
    with heading:
        st.header('市场概览')
    with action:
        update = st.button('更新数据', key='refresh_home')
    if update:
        with st.spinner('正在更新市场与政策…'):
            refreshed = read_home_sections(data, refresh=True)
        invalidate()
        if any(not isinstance(x['result'], Exception) and not x['result'].get('stale') for x in refreshed.values()):
            st.success('数据已更新')
        else:
            st.caption('暂未取得新数据，保留已有记录。')
    sections = remember('home', lambda: read_home_sections(data))
    def read(name):
        value = sections[name]['result']
        return None if isinstance(value, Exception) else value
    indices, spot, policies = (read(name) for name in ('indices', 'spot', 'policies'))
    if indices:
        data_meta(indices)
        metrics = []
        for item in indices['items'][:3]:
            change = number(item.get('change_pct'))
            change_text = '—' if change is None else f'{change:+.2f}%'
            metrics.append((item['name'], fmt(item.get('price')), change_text+' · '+date_label(item.get('date')),
                            'up' if change is not None and change >= 0 else 'down' if change is not None else ''))
        metric_grid(metrics)
    else:
        st.caption('数据状态 · 指数日线待更新')
        empty_state('市场数据待更新', '已有研究不受影响，可稍后手动更新。')

    st.subheader('我的研究')
    left, right = st.columns(2, gap='large')
    with left:
        st.markdown('**我的自选**')
        watchlist = repo.list('watchlist_items', limit=5)
        if not watchlist:
            empty_state('还没有自选', '在个股研究页关注一家公司。')
        for record in watchlist:
            item = record['payload']
            st.write(item['name'])
            st.caption(item['code'])
    with right:
        st.markdown('**最近研究**')
        reports = repo.list('research_reports', limit=3)
        if not reports:
            empty_state('从一家公司开始', '已保存的研究会显示在这里。')
        for record in reports:
            report = record['payload']
            with st.expander(report.get('question') or report.get('purpose', '研究报告')):
                st.caption(date_label(record['created_at'])+' · 历史研究')
                st.markdown(report.get('answer', ''))

    st.subheader('政策观察')
    if policies:
        data_meta(policies)
        policy_cards(policies['items'])
    else:
        empty_state('暂无政策记录', '仅展示官方发布内容。')
    if spot:
        with st.expander('实时市场快照'):
            data_meta(spot)
            changes = [number(x.get('change_pct')) for x in spot['items']]
            changes = [x for x in changes if x is not None]
            st.write(f'上涨 {sum(x > 0 for x in changes)} · 下跌 {sum(x < 0 for x in changes)} · 平盘 {sum(x == 0 for x in changes)}')
            st.caption('按已返回股票汇总，非交易所完整市场口径。')
    else:
        st.caption('实时市场快照暂不可用')
    evidence = {}
    if indices:
        evidence['indices'] = indices
    if spot:
        evidence['market_snapshot'] = {k: v for k, v in spot.items() if k != 'items'} | {
            'up': sum(x > 0 for x in changes), 'down': sum(x < 0 for x in changes)}
    if policies:
        evidence['policies'] = policies
    if evidence:
        with st.expander('市场研究'):
            ai_button(ai, 'market', '生成市场简报', evidence, level=level)

"""Personal watchlist and research library; reads existing user-owned storage only."""
import streamlit as st
from ..data import DataUnavailable, number
from .components import section_intro, research_card, empty_state, fmt, data_meta, date_label
from .navigation import open_stock, open_page
from .reads import remember


def watch_cards(data, repo, limit=100, prefix='watch'):
    records = repo.list('watchlist_items', limit=limit)
    reports = repo.list('research_reports', limit=100)
    latest = {}
    for record in reports:
        report = record['payload']
        if report.get('code'):latest.setdefault(report['code'], report)
    # This method is already cache-only; never start a market provider from a watchlist.
    try:quotes = remember('watch_quotes', data.spot)
    except DataUnavailable:quotes = None
    mapping = {x['code']: x for x in quotes['items']} if quotes else {}
    if not records:
        empty_state('你的观察清单，从一家公司开始', '在个股页加入自选；已有研究不会自动触发任何付费调用。')
        st.button('寻找研究对象', key=prefix+'_find', on_click=open_page, args=('个股',))
    for i, record in enumerate(records):
        item = record['payload'];code = item['code'];quote = mapping.get(code, {})
        with st.container(border=True):
            change = number(quote.get('change_pct'))
            tone = 'up' if change is not None and change > 0 else 'down' if change is not None and change < 0 else 'neutral'
            research_card(item.get('name', code), code+' · 自选观察',
                          '最近研究 '+date_label(latest[code].get('created_at')) if code in latest else '尚无公司研究报告',
                          '研究已保存' if code in latest else '待研究')
            from .components import metric_grid
            metric_grid([('已有价格', fmt(quote.get('price'), ' 元'), '实时价格缺失时保持空白', ''),
                         ('涨跌幅', fmt(change, '%'), '上次保存的行情，非实时' if quote else '暂无可靠快照', tone)], columns=2)
            if quote:data_meta(quotes)
            st.button('查看研究', key=prefix+'_open_'+str(i), on_click=open_stock, args=(code,))
            if prefix == 'watch':
                if st.button('移出自选', key='remove_watch_'+record['key']):
                    repo.remove('watchlist_items', record['key']);st.rerun()
    return records


def watchlist(data, repo):
    section_intro('WATCHLIST', '自选观察', '把注意力留给你真正想理解的公司。价格缺失不影响研究。')
    with st.expander('观察分组与追踪计划'):
        st.caption('当前为全部自选；长线 / 中线 / 短线 / 主题分组规划中，尚未启用。')
    watch_cards(data, repo)


def report_cards(repo, limit=6, prefix='report', library=False):
    records = repo.list('research_reports', limit=limit)
    if not records:empty_state('还没有研究报告', '进入个股的AI研究页签，基于已保存资料生成。')
    for i, record in enumerate(records):
        report = record['payload']
        with st.container(border=True):
            research_card(report.get('question') or '研究报告', report.get('model') or '历史研究',
                          '生成于 '+date_label(report.get('created_at') or record['created_at']), '已保存 · 非实时观点')
            if library:
                if st.button('阅读报告', key=prefix+'_read_'+str(i)):
                    st.session_state['selected_report'] = record['key']
            elif report.get('code'):
                st.button('打开AI研究', key=prefix+'_open_'+str(i), on_click=open_stock, args=(report['code'], True))
            else:
                st.button('前往研究库', key=prefix+'_library_'+str(i), on_click=open_page, args=('AI研究',))
    return records


def research_library(repo):
    from .report_view import render_report, followup_placeholder
    section_intro('RESEARCH LIBRARY', 'AI研究', '从真实资料到可核对的观点。这里汇集你已保存的研究，不自动发起AI调用。')
    st.button('研究一家公司', type='primary', on_click=open_page, args=('个股',))
    query = st.text_input('检索研究报告', placeholder='公司名称、代码或研究主题')
    records = repo.list('research_reports', limit=100)
    # Keep search local and user-scoped; never fetch company facts for a library listing.
    matches = [r for r in records if not query or query.lower() in str(r['payload'].get('question', '')).lower()
               or query in str(r['payload'].get('code', ''))]
    if not matches:empty_state('暂无匹配的研究', '选择一家公司开始，或调整检索关键词。')
    for i, record in enumerate(matches):
        report = record['payload']
        with st.container(border=True):
            research_card(report.get('question') or '历史研究', 'DeepSeek · 研究档案',
                          '生成于 '+date_label(report.get('created_at') or record['created_at']), '已保存')
            if st.button('阅读报告', key='library_read_'+str(i)):st.session_state['selected_report'] = record['key']
    selected = st.session_state.get('selected_report')
    record = repo.get('research_reports', selected) if selected in {r['key'] for r in matches} else None
    if record:
        st.divider()
        if record.get('report'):render_report(record)
        else:
            st.subheader(record.get('question') or '历史研究')
            st.caption('历史研究，不代表最新数据或当前观点。')
            st.markdown(record.get('answer', ''))
        if record.get('code'):
            st.button('查看公司最新研究资料', on_click=open_stock, args=(record['code'], True))
    followup_placeholder('library')

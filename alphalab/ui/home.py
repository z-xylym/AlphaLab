import streamlit as st
from ..data import read_home_sections, number
from .components import data_meta, date_label, empty_state, fmt, metric_grid, section_intro, research_card
from .reads import remember, invalidate


def policy_cards(items):
    for policy in items[:3]:
        with st.container(border=True):
            research_card(policy['title'], date_label(policy.get('published_at'))+' · '+policy.get('publisher', '中国政府网'),
                          '官方政策索引，具体措施与生效状态请核对原文。', '政策观察')
            st.link_button('阅读官方原文', policy['url'])


def market_overview(data):
    with st.container(key='market_header'):
        heading, action = st.columns([4, 1], vertical_alignment='center')
        with heading:st.header('市场概览')
        with action:update = st.button('更新数据', key='refresh_home')
    if update:
        with st.spinner('正在更新市场与政策…'):refreshed = read_home_sections(data, refresh=True)
        invalidate()
        if any(not isinstance(x['result'], Exception) and not x['result'].get('stale') for x in refreshed.values()):st.success('数据已更新')
        else:st.caption('暂未取得新数据，保留已有记录。')
    st.caption('指数采用最近已发布的每日收盘记录，不是实时行情。')
    sections = remember('home', lambda: read_home_sections(data))
    def read(name):
        value = sections[name]['result']
        return None if isinstance(value, Exception) else value
    indices, policies = read('indices'), read('policies')
    # Keep three stable positions even if an individual source/cache is unavailable.
    available = {r['code']: r for r in indices['items']} if indices else {}
    metrics = []
    for code, name in (('sh000001', '上证指数'), ('sz399001', '深证成指'), ('sz399006', '创业板指')):
        item = available.get(code, {})
        change = number(item.get('change_pct'))
        state = '历史缓存' if item.get('stale') else '已保存日线' if item else '待更新'
        metrics.append((name, fmt(item.get('price')), ('—' if change is None else f'{change:+.2f}%')+' · '+date_label(item.get('date'))+' · '+state,
                        'up' if change is not None and change > 0 else 'down' if change is not None and change < 0 else 'neutral'))
    with st.container(key='market_metrics'):metric_grid(metrics)
    if indices:data_meta(indices)
    else:st.caption('数据状态 · 指数日线待更新；已有研究不受影响。')
    return policies


def home(data, repo, ai, level):
    from .workspace import watch_cards, report_cards
    from .preferences import preferences_form
    profile=repo.get('user_preferences','profile',{})
    if not profile.get('onboarding_completed'):
        preferences_form(repo,data,profile,onboarding=True)
    section_intro('YOUR PRIVATE RESEARCH SPACE', '让研究，井然有序。', '关注真实数据，沉淀独立判断。你的公司观察与研究记录，都在这里。')
    from .recommendations import recommendations
    recommendations(data,repo)
    policies = market_overview(data)
    with st.container(key='home_personal'):
        left, right = st.columns(2, gap='large')
        with left:
            st.subheader('我的自选')
            watch_cards(data, repo, limit=3, prefix='home_watch')
        with right:
            st.subheader('最近研究')
            report_cards(repo, limit=3, prefix='home_report')
    st.subheader('政策观察')
    if policies:
        data_meta(policies)
        policy_cards(policies['items'])
    else:empty_state('暂无政策记录', '仅展示官方发布内容，不影响其他研究模块。')

import streamlit as st
from .components import section_intro
from .discovery import sectors, screener
from .home import market_overview, policy_cards


def market(data, repo, ai, level):
    section_intro('MARKET OBSERVATORY', '市场', '先看环境，再看行业与研究条件。历史指数不代表实时行情。')
    section = st.radio('市场内容', ['市场概览', '行业观察', '选股观察'], horizontal=True, key='market_section')
    if section == '行业观察':sectors(data, repo, ai, level)
    elif section == '选股观察':screener(data, repo, ai, level)
    else:
        policies = market_overview(data)
        st.subheader('政策观察')
        if policies:policy_cards(policies['items'])
        else:st.caption('暂无可靠政策缓存，可手动更新后查看。')

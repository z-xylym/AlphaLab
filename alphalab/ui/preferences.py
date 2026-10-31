"""Private preferences reused by first-visit onboarding and account settings."""
import streamlit as st
from ..personalization import INTERESTS, PERIODS, industry_catalog
from .reads import cached_catalog
from .components import section_intro


def preferences_form(repo, data, profile=None, onboarding=False):
    profile = profile or {}
    catalog, _ = cached_catalog(data.db)
    choices = sorted(set(INTERESTS) | set(catalog['industries']) | set(profile.get('industries', [])))
    if onboarding:
        section_intro('WELCOME TO ALPHALAB', '先告诉我们，你想研究什么', '选几个关注方向，首页会解释哪些公司值得你进一步了解。随时可在“我的”修改。')
    with st.form('research_preferences'):
        industries = st.multiselect('关注行业（可多选）', choices, default=profile.get('industries', []), placeholder='选择关注行业，可多选',
                                    help='这是你的关注方向，不代表系统已有这些行业的完整数据；缺失分类不会由AI猜测。')
        period = st.radio('研究周期', list(PERIODS), index=list(PERIODS).index(profile.get('period', '都看看')) if profile.get('period', '都看看') in PERIODS else 3, horizontal=True)
        goal = st.text_input('一句话诉求', value=profile.get('goal', ''), max_chars=200,
                             placeholder='例如：想找经营稳健、适合长期观察的公司。')
        level = profile.get('level', '零基础')
        if not onboarding:
            level = st.selectbox('知识水平', ['零基础', '进阶', '专业'], index=['零基础', '进阶', '专业'].index(level) if level in ('零基础', '进阶', '专业') else 0)
        saved = st.form_submit_button('开始我的研究' if onboarding else '保存偏好', type='primary')
    if saved:
        repo.put('user_preferences', 'profile', {**profile, 'level': level, 'industries': industries,
                 'period': period, 'goal': goal.strip()[:200], 'onboarding_completed': True})
        st.rerun()

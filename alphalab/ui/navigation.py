"""UI-only routes; callbacks run before widgets are constructed on the next rerun."""
import streamlit as st

NAVIGATION = ['首页', '市场', '自选', '个股', 'AI研究', '我的']


def open_stock(code, ai=False):
    st.session_state['navigation'] = '个股'
    st.session_state['research_query'] = code
    st.session_state['stock_query'] = code
    st.session_state['research_tab'] = 'AI研究' if ai else '概览'


def open_page(page):
    st.session_state['navigation'] = page

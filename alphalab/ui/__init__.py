"""Application shell; financial, auth and database behavior stays in existing modules."""
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
from ..config import Settings, SetupRequired, UserError
from ..auth import Auth
from ..repository import Repository
from ..data import MarketData
from ..ai import AI
from .components import STYLES, DISCLAIMER, brand
from .login import login_screen
from .home import home
from .stock import stock_research
from .market import market
from .workspace import watchlist, research_library
from .navigation import NAVIGATION
from .account import mine
from .admin import admin_security_master


def main():
    st.set_page_config(page_title='AlphaLab · 私人投研终端', layout='wide', initial_sidebar_state='collapsed')
    st.html('<style>'+STYLES.read_text()+'</style>')
    try:
        settings = Settings.load(st.secrets)
        auth = Auth(settings)
        token = st.session_state.get('token')
        if not token:
            login_screen(auth)
            return
        user = auth.current(token)
        repo = Repository(auth, token)
        data = MarketData(auth.db)
        ai = AI(repo, settings)
        pref = repo.get('user_preferences', 'profile', {'level': '零基础'})
        with st.container(key='topbar'):
            identity, navigation = st.columns([2, 3], vertical_alignment='center')
            with identity:
                brand()
            with navigation:
                with st.container(key='primary_nav'):
                    page = st.radio('导航', NAVIGATION,
                                    horizontal=True, label_visibility='collapsed', key='navigation')
        if page == '首页':
            home(data, repo, ai, pref['level'])
        elif page == '市场':
            market(data, repo, ai, pref['level'])
        elif page == '自选':
            watchlist(data, repo)
        elif page == 'AI研究':
            research_library(repo)
        elif page == '个股':
            stock_research(data, repo, ai, pref['level'])
        else:
            mine(data, repo, ai, auth, user, pref)
    except (UserError, SetupRequired) as exc:
        st.warning(str(exc))
        if '会话已过期' in str(exc):
            st.session_state.clear()
            if st.button('返回登录'):
                st.rerun()
    except SQLAlchemyError:
        st.error('数据库安全连接配置未完成或数据库暂时不可用。请检查部署平台的官方 CA 和连接配置。')
    except Exception:
        st.error('服务暂不可用，请稍后重试。')
    finally:
        st.divider()
        st.caption(DISCLAIMER)

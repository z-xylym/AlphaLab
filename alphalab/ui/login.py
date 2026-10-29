import streamlit as st
from ..config import UserError
from .components import brand


def login_screen(auth):
    with st.container(key='login'):
        brand()
        st.title('私人投资研究空间')
        st.write('把市场、公司与研究放在同一个地方。')
        with st.form('login', border=False):
            phone = st.text_input('手机号', max_chars=16)
            password = st.text_input('密码', type='password', max_chars=128)
            submitted = st.form_submit_button('登录', type='primary', use_container_width=True)
        if submitted:
            st.session_state['token'] = auth.login(phone, password)
            st.rerun()
        with st.expander('邀请注册'):
            with st.form('register', border=False):
                phone = st.text_input('受邀手机号', max_chars=16)
                code = st.text_input('邀请码', type='password')
                password = st.text_input('设置密码（至少12字符）', type='password', max_chars=128)
                repeat = st.text_input('重复密码', type='password', max_chars=128)
                submitted = st.form_submit_button('创建账户')
            if submitted:
                if password != repeat:
                    raise UserError('两次密码不一致。')
                auth.register(phone, password, code)
                st.success('注册成功，请登录。')
        st.caption('仅接受邀请注册。手机号用作登录标识，不验证号码归属。')

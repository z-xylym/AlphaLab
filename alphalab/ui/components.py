"""Small shared presentation components. Dynamic HTML is always escaped."""
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import streamlit as st
from ..data import DataUnavailable, number

STYLES = Path(__file__).resolve().parents[2] / 'assets' / 'styles.css'
DISCLAIMER = '仅供学习与研究，不构成投资建议。模拟交易不连接证券账户。'


def brand():
    st.html('<div class="brand">AlphaLab<span>Private Investment Research</span></div>')


def date_label(value):
    if not value:
        return '—'
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo:
            parsed = parsed.astimezone(ZoneInfo('Asia/Shanghai'))
        return parsed.strftime('%Y-%m-%d')
    except ValueError:
        return text[:10] if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', text) else '—'


def time_label(value):
    if not value:return '—'
    try:
        parsed=datetime.fromisoformat(str(value))
        if parsed.tzinfo:parsed=parsed.astimezone(ZoneInfo('Asia/Shanghai'))
        return parsed.strftime('%Y-%m-%d %H:%M')
    except ValueError:return date_label(value)


def source_label(data):
    text = str(data.get('provider') or data.get('source') or '')
    for needle, label in (('gov.cn', '中国政府网'), ('主营', '东方财富主营构成'),
                          ('财务', '新浪财务摘要'), ('证券', '交易所证券名单'),
                          ('指数', '新浪指数日线'), ('日线', '新浪日线')):
        if needle in text:
            return label
    return '公开数据'


def data_meta(data, price_missing=False):
    if not data:
        return
    stale = '<span class="status-tag">历史缓存</span>' if data.get('stale') else '<span class="status-tag neutral">已保存</span>'
    price = '<span class="status-tag neutral">实时价格暂不可用</span>' if price_missing else ''
    st.html(f'<div class="data-meta">{escape(source_label(data))} · 更新于 '
            f'{escape(time_label(data.get("fetched_at")))} {stale} {price}</div>')


source = data_meta


def empty_state(title, detail=''):
    st.html(f'<div class="empty-state"><strong>{escape(title)}</strong>'
            f'<span>{escape(detail)}</span></div>')


def fmt(value, suffix=''):
    n = number(value)
    return '—' if n is None else f'{n:,.2f}{suffix}'


def metric_grid(items, columns=3):
    """(label, value, subtext, direction) tuples; no untrusted markup."""
    cells = []
    for label, value, subtext, direction in items:
        tone = direction if direction in ('up','down','neutral') else ('neutral' if str(value)=='—' else '')
        note=escape(str(subtext))
        if tone and re.match(r'[+-]\d',str(subtext)):
            first,sep,rest=str(subtext).partition(' · ')
            note=f'<span class="{tone}">{escape(first)}</span>'+(' · '+escape(rest) if sep else '')
        cells.append(f'<div class="metric-cell"><span class="metric-label">{escape(str(label))}</span>'
                     f'<strong class="metric-value {tone}">{escape(str(value))}</strong><span class="metric-sub">'
                     f'{note}</span></div>')
    st.html(f'<div class="metric-grid cols-{int(columns)}">'+''.join(cells)+'</div>')


def show_stock(x):
    st.markdown(f"**{x.get('name','')} · {x.get('code','')}**")
    change = number(x.get('change_pct'))
    st.caption('最新可用价格 '+fmt(x.get('price'), ' 元'))
    if change is not None:
        st.markdown(f":{'red' if change > 0 else 'green'}[{change:+.2f}%]") if change else st.caption('平盘 0.00%')
    if x.get('reason'):
        st.write(x['reason'])
    if x.get('risk'):
        st.caption(x['risk'])


def ai_button(ai, purpose, label, evidence, question='', level='零基础', key=None):
    key = key or purpose
    if st.button(label, key='generate_'+key, type='primary'):
        with st.spinner('正在生成研究…'):
            answer, cached = ai.generate(purpose, question, evidence, level)
            st.session_state['answer_'+key] = answer
            st.caption('已读取今日研究。' if cached else '已保存到研究历史。')
    if 'answer_'+key in st.session_state:
        st.markdown(st.session_state['answer_'+key])
        st.caption('辅助研究，数据与原文仍需核对。')


def fetch_panel(loader):
    try:
        result = loader()
        data_meta(result)
        return result
    except DataUnavailable:
        empty_state('数据暂不可用')
        return None


@lru_cache(maxsize=1)
def chart_tokens():
    return dict(re.findall(r'--([\w-]+):\s*([^;]+);', STYLES.read_text()))


def chart_style(figure):
    tokens = chart_tokens()
    figure.update_layout(template='plotly_white', height=340,
                         paper_bgcolor=tokens['surface'], plot_bgcolor=tokens['surface'],
                         font_color=tokens['text-muted'], font_family='Arial, sans-serif',
                         margin=dict(l=8, r=12, t=16, b=12),
                         colorway=[tokens['accent']], showlegend=False,
                         xaxis=dict(title=None, showgrid=False),
                         yaxis=dict(gridcolor=tokens['border'], zeroline=False))
    figure.update_traces(line_color=tokens['accent'])
    return figure


def section_intro(eyebrow, title, detail):
    st.html(f'<div class="section-intro"><span>{escape(eyebrow)}</span>'
            f'<h2>{escape(title)}</h2><p>{escape(detail)}</p></div>')


def research_card(title, subtitle, detail='', status=''):
    st.html(f'<div class="research-card"><div class="card-eyebrow">{escape(subtitle)}</div>'
            f'<strong>{escape(title)}</strong><p>{escape(detail)}</p>'
            f'<span class="status-tag neutral">{escape(status)}</span></div>')


def planned_panel(title, detail):
    with st.container(border=True):
        st.caption('规划中 · 尚未启用')
        st.markdown('**'+title+'**')
        st.caption(detail)

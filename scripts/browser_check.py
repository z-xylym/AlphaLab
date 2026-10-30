"""Responsive UI check: isolated test DB/fixtures, never production data or AI."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import httpx
import pgserver
from playwright.sync_api import sync_playwright
from alphalab.config import Settings
from alphalab.auth import Auth
from alphalab.repository import Repository
from alphalab.db import metadata, engine_for, today
from alphalab.data import MarketData

ROOT = Path(__file__).resolve().parents[1]


def seed(auth, token):
    """Clearly labelled layout fixtures exist only in this script's temporary DB."""
    from datetime import timedelta
    data = MarketData(auth.db)
    def put(key, items, source):
        data.cached(key, 3600, source+'（浏览器测试夹具，非生产数据）', lambda: {'items': items})
    put('master:v1:SH', [{'code': '600519', 'name': '贵州茅台', 'exchange': 'SH', 'price': None,
                         'listing_date': '2001-08-27','industry':'食品饮料'}], '证券名单')
    put('master:v1:SZ',[{'code':'000001','name':'示例银行（隔离夹具）','exchange':'SZ','industry':'银行','price':None}], '证券名单')
    put('financial:000001',[{'指标':label,'20251231':value} for label,value in [('净利润（元）',20),('净资产收益率（%）',10),('经营活动现金流量净额（元）',25)]], '新浪财务摘要')
    put('history:600519:20200101:'+today().strftime('%Y%m%d'), [
        {'date': str(today()-timedelta(days=120-i)), 'open': 100+i*.1, 'close': 101+i*.1,
         'high': 102+i*.1, 'low': 99+i*.1, 'volume': 1000} for i in range(120)], '新浪日线')
    put('financial:600519', [{'指标': label, '20251231': value} for label, value in (
        ('营业收入(元)', 100), ('归母净利润(元)', 20), ('净资产收益率(ROE)(%)', 10),
        ('销售毛利率(%)', 50), ('资产负债率(%)', 30), ('经营活动产生的现金流量净额(元)', 15))], '新浪财务摘要')
    put('business:600519', [{'主营构成': '测试产品（非真实披露）', '分类类型': '按产品', '主营收入': 100,
                           '报告日期': '2025-12-31'}], '东方财富主营')
    for code, name in [('sh000001', '上证指数'), ('sz399001', '深证成指'), ('sz399006', '创业板指')]:
        put('index:sina:'+code, [{'code': code, 'name': name, 'price': 3000, 'change_pct': 1.23,
                                'date': str(today()-timedelta(days=1))}], '新浪指数日线')
    put('policies:v2', [{'title': '政策索引布局测试记录（非真实政策）', 'published_at': str(today()),
                        'publisher': '中国政府网（测试标识）', 'content': '仅测试排版，不代表真实政策。',
                        'url': 'https://www.gov.cn/zhengce/zuixin/'}], '中国政府网')
    repo = Repository(auth, token)
    repo.put('research_reports', 'layout-report', {'question': '贵州茅台 · 浏览器测试报告', 'purpose': 'stock',
             'answer': '浏览器布局测试夹具，非真实研究结论。\n\n' * 12})
    from alphalab.research_context import build_context
    from alphalab.company_report import SECTIONS, payload, request_key
    from alphalab.db import now
    stock=data.search('600519')[0]
    context=build_context(stock,data.company('600519'),data.financials('600519'),data.history('600519'),
                          data.business('600519'),data.policies())
    answer=json.dumps({'sections':[{'title':title,'facts':['隔离浏览器测试资料，不代表真实公司事实。'],
                                    'analysis':['仅验证报告排版；不生成真实研究或投资结论。'],
                                    'missing_data':['实时价格、PE/PB未提供。']} for title in SECTIONS]})
    repo.put('research_reports',request_key(context,'deepseek-chat'),payload(context,answer,'deepseek-chat',now().isoformat()))



def main():
    output = ROOT/'test-results'
    output.mkdir(exist_ok=True)
    pg = pgserver.get_server(Path(tempfile.mkdtemp(prefix='alphalab-browser-db-')), cleanup_mode='delete')
    url = pg.get_uri().replace('postgresql://', 'postgresql+psycopg://', 1)
    password = secrets.token_urlsafe(24)
    settings = Settings(database_url=url, app_secret_key=secrets.token_hex(32),
                        admin_phone='13800000009', admin_initial_password=password)
    metadata.create_all(engine_for(url))
    auth = Auth(settings)
    auth.bootstrap()
    token = auth.login('13800000009', password)
    seed(auth, token)
    helper = output/'offline_app.py'
    helper.write_text('''import streamlit as st
from alphalab import provider
from alphalab.ui import main
def denied(*a, **k):
    raise RuntimeError("Browser test forbids upstream calls")
provider.call = denied
st.html('<div style="position:fixed;bottom:0;left:0;right:0;text-align:center;background:#fff8e8;color:#6d542d;font-size:11px;z-index:9999;padding:3px">浏览器布局测试 · 隔离夹具，非生产行情或投资结论</div>')
main()
''')
    env = os.environ.copy()
    env.update(DATABASE_URL=url, APP_SECRET_KEY=settings.app_secret_key, PYTHONPATH=str(ROOT),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    log = (output/'browser-server.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(helper),
                                '--server.address', '127.0.0.1', '--server.port', '8502'],
                               cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        for _ in range(60):
            try:
                if httpx.get('http://127.0.0.1:8502/_stcore/health', trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            results = []
            for width in (1440, 390, 430):
                # Reset only this disposable fixture user's preferences/watchlist for each first-visit run.
                fixture_repo=Repository(auth,token)
                fixture_repo.remove('user_preferences','profile')
                fixture_repo.remove('watchlist_items')
                page = browser.new_page(viewport={'width': width, 'height': 1000 if width == 1440 else 844})
                timings = {}
                def ready():
                    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=20000)
                    page.locator('[data-testid="stStatusWidget"]').wait_for(state='hidden', timeout=20000)
                def capture(name):
                    ready()
                    page.locator('[data-testid="stMain"]').evaluate('(element) => element.scrollTop = 0')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name
                    assert page.locator('[data-testid="stMain"]').evaluate('(el) => el.scrollWidth <= el.clientWidth'), name
                    buttons = page.get_by_role('button').evaluate_all('''elements => elements.map(el => ({text:el.innerText.trim(), height:el.getBoundingClientRect().height}))''')
                    for button in buttons:
                        if button['height'] and button['text'] in (
                            '登录', '搜索', '加入自选', '更新数据', '更新研究数据', '生成AI研究', '退出登录'):
                            assert button['height'] >= 44, button['text']
                    if page.get_by_role('radiogroup', name='导航', exact=True).count():
                        for label in ('首页', '市场', '自选', '个股', 'AI研究', '我的'):
                            box = page.get_by_role('radiogroup', name='导航', exact=True).get_by_text(label, exact=True).bounding_box()
                            assert box['x'] >= 0 and box['x']+box['width'] <= width, label
                        labels = page.get_by_role('radiogroup', name='导航', exact=True).locator('label').evaluate_all('elements => elements.map(el => el.getBoundingClientRect().height)')
                        assert all(height >= 44 for height in labels)
                    page.screenshot(path=str(output/f'{name}-{width}.png'), full_page=True)
                def nav(name):
                    page.get_by_role('radiogroup', name='导航', exact=True).get_by_text(name, exact=True).click()
                    ready()
                def research_tab(name):
                    page.get_by_role('radiogroup', name='研究内容', exact=True).get_by_text(name, exact=True).click()
                    ready()
                page.goto('http://127.0.0.1:8502', wait_until='networkidle')
                page.get_by_role('heading', name='私人投资研究空间', exact=True).wait_for()
                capture('login')
                page.get_by_role('textbox', name='手机号', exact=True).fill('13800000009')
                page.get_by_role('textbox', name='密码', exact=True).fill(password)
                started = time.perf_counter()
                page.get_by_role('button', name='登录', exact=True).click()
                page.get_by_role('heading', name='市场概览', exact=True).wait_for(timeout=20000)
                ready()
                timings['initial_home_seconds'] = round(time.perf_counter()-started, 3)
                capture('home')
                # Complete real onboarding through the UI, without seeded private preferences.
                page.get_by_role('button',name='开始我的研究',exact=True).wait_for()
                capture('onboarding')
                interests=page.get_by_role('combobox').first
                interests.fill('食品饮料')
                page.get_by_role('option',name='食品饮料',exact=True).click()
                interests.fill('银行')
                page.get_by_role('option',name='银行',exact=True).click()
                interests.press('Escape')
                page.get_by_role('radiogroup',name='研究周期',exact=True).get_by_text('长期',exact=True).click()
                page.get_by_role('textbox',name='一句话诉求',exact=True).fill('想找经营稳健、适合长期观察的公司。')
                page.get_by_role('button',name='开始我的研究',exact=True).click()
                page.get_by_role('button',name='开始我的研究',exact=True).wait_for(state='hidden')
                page.get_by_role('heading',name='为你推荐',exact=True).wait_for()
                ready()
                page.get_by_role('button',name='加入关注',exact=True).first.click()
                page.locator('.st-key-home_watch_open_0 button').wait_for()
                ready()
                capture('personalized-home')
                assert page.get_by_role('button',name='已关注',exact=True).count()>=1
                # The navigation has a real checked state, not decorative HTML links.
                assert page.get_by_role('radio', name='首页', exact=True).is_checked()
                nav('自选')
                page.get_by_role('heading', name='自选观察', exact=True).wait_for()
                capture('watchlist')
                nav('AI研究')
                page.get_by_role('heading', name='AI研究', exact=True).wait_for()
                page.get_by_role('button', name='阅读报告', exact=True).first.click()
                ready()
                from alphalab.company_report import SECTIONS
                page.get_by_role('heading',name=SECTIONS[0],exact=True).wait_for(timeout=20000)
                ready()
                for title in SECTIONS:
                    assert page.get_by_role('heading',name=title,exact=True).count()==1
                capture('research-library')
                nav('市场')
                page.get_by_role('heading', name='市场', exact=True).wait_for()
                capture('market')
                page.get_by_role('radiogroup',name='市场内容',exact=True).get_by_text('行业观察',exact=True).click()
                page.get_by_role('textbox',name='搜索行业',exact=True).fill('银行')
                page.get_by_role('textbox',name='搜索行业',exact=True).press('Enter')
                page.locator('.st-key-industry_open_000001 button').wait_for()
                ready()
                capture('industry-bank')
                page.locator('.st-key-industry_open_000001 button').click()
                page.get_by_role('heading',name='示例银行（隔离夹具）',exact=True).wait_for()
                nav('个股')
                page.get_by_role('textbox', name='股票名称或代码', exact=True).fill('600519')
                started = time.perf_counter()
                page.get_by_role('button', name='搜索', exact=True).click()
                page.get_by_role('heading', name='贵州茅台', exact=True).wait_for(timeout=20000)
                ready()
                timings['search_cached_stock_seconds'] = round(time.perf_counter()-started, 3)
                capture('stock-overview')
                research_tab('走势')
                page.locator('[data-testid="stPlotlyChart"]').wait_for(timeout=20000)
                ready()
                chart = page.locator('[data-testid="stPlotlyChart"]').bounding_box()
                assert chart['x'] >= 0 and chart['x']+chart['width'] <= width+1
                capture('stock-chart')
                research_tab('财务')
                page.get_by_text('指标口径与原始摘要', exact=True).wait_for()
                capture('stock-financials')
                research_tab('主营')
                page.locator('[data-testid="stDataFrame"]').wait_for()
                capture('stock-business')
                research_tab('AI研究')
                page.get_by_role('button', name='生成AI研究', exact=True).wait_for()
                page.get_by_role('heading',name=SECTIONS[0],exact=True).wait_for(timeout=20000)
                ready()
                for title in SECTIONS:
                    assert page.get_by_role('heading',name=title,exact=True).count()==1
                capture('stock-ai')
                research_tab('预警')
                page.get_by_role('heading', name='预警与跟踪', exact=True).wait_for()
                capture('stock-alerts')
                nav('我的')
                page.get_by_role('heading', name='我的', exact=True).wait_for()
                capture('mine')
                started = time.perf_counter()
                nav('个股')
                page.get_by_role('heading', name='贵州茅台', exact=True).wait_for(timeout=20000)
                ready()
                timings['reopen_cached_stock_seconds'] = round(time.perf_counter()-started, 3)
                # Server side role, diagnostics and logout are still reachable inside My account.
                nav('我的')
                page.get_by_role('combobox').click()
                page.get_by_role('option', name='管理后台', exact=True).click()
                page.get_by_role('heading', name='基础证券名单', exact=True).wait_for()
                capture('admin')
                results.append({'width': width, 'horizontal_overflow': False, 'navigation_active': True,
                                'button_touch_height': '>=44px', 'fixture_only': True, **timings})
                page.close()
            browser.close()
        (output/'terminal-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(results, ensure_ascii=False))
    finally:
        process.terminate()
        process.wait(timeout=15)
        log.close()


if __name__ == '__main__':
    main()

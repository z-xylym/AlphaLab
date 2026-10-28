"""Mobile layout integration test. Temporary DB/accounts, unavailable external data; no synthetic quotes."""
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
from alphalab.db import metadata,engine_for

root=Path(__file__).resolve().parents[1]

def main():
    output=root/'test-results'
    output.mkdir(exist_ok=True)
    pg=pgserver.get_server(Path(tempfile.mkdtemp(prefix='alphalab-browser-db-')),cleanup_mode='delete')
    url=pg.get_uri().replace('postgresql://','postgresql+psycopg://',1)
    key=secrets.token_hex(32);password=secrets.token_urlsafe(24)
    s=Settings(database_url=url,app_secret_key=key,admin_phone='13800000009',admin_initial_password=password)
    metadata.create_all(engine_for(url));auth=Auth(s);auth.bootstrap()
    token=auth.login('13800000009',password)
    Repository(auth,token).put('research_reports','layout-report',{'question':'长报告布局测试（测试夹具）','purpose':'stock','answer':('已核实事实：这里只是浏览器布局测试文字，不是投资研究结论。\n\n' * 35)})
    helper=output/'offline_app.py'
    helper.write_text('''from alphalab.data import MarketData, DataUnavailable
from alphalab.ui import main
def unavailable(*a,**k): raise DataUnavailable("浏览器测试：外部源不可用")
for name in ("indices","spot","policies","sectors","company","financials","business"):
    setattr(MarketData,name,unavailable)
def fixture(items):
    return {"items":items,"source":"浏览器布局测试夹具，非真实行情","fetched_at":"2026-01-01T00:00:00+00:00","stale":False}
MarketData.spot=lambda self:fixture([{"code":"600001","name":"布局测试夹具（非真实股票）","price":10,"change_pct":1,"turnover":10000000}])
MarketData.history=lambda self,*a:fixture([{"date":f"2026-01-{i:02d}","close":10+i/100,"open":10,"high":11,"low":9,"volume":1000} for i in range(1,15)])
main()
''')
    env=os.environ.copy()
    env.update(DATABASE_URL=url,APP_SECRET_KEY=key,PYTHONPATH=str(root),STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    log=(output/'browser-server.log').open('w')
    process=subprocess.Popen([sys.executable,'-m','streamlit','run',str(helper),
        '--server.address','127.0.0.1','--server.port','8502'],cwd=root,env=env,stdout=log,stderr=log)
    try:
        for _ in range(50):
            try:
                if httpx.get('http://127.0.0.1:8502/_stcore/health',trust_env=False).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.2)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
            results=[]
            for width in (375,390,430):
                page=browser.new_page(viewport={'width':width,'height':844},device_scale_factor=1)
                page.goto('http://127.0.0.1:8502',wait_until='networkidle')
                page.get_by_role('heading',name='欢迎回到你的研究空间').wait_for()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/f'login-{width}.png'),full_page=True)
                page.get_by_role('textbox',name='手机号',exact=True).fill('13800000009')
                page.get_by_role('textbox',name='密码',exact=True).fill(password)
                page.get_by_role('button',name='登录',exact=True).click()
                page.get_by_role('heading',name='每天，看懂一点市场。').wait_for(timeout=20000)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                page.get_by_role('combobox').first.click()
                page.get_by_role('option',name='我的',exact=True).click()
                page.get_by_role('heading',name='我的持仓',exact=True).wait_for()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/f'portfolio-{width}.png'),full_page=True)
                page.get_by_role('combobox').nth(1).click()
                page.get_by_role('option',name='个人设置',exact=True).click()
                page.get_by_text('知识水平',exact=True).wait_for()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.get_by_role('combobox').first.click()
                page.get_by_role('option',name='个股',exact=True).click()
                page.get_by_role('textbox',name='输入股票名称、代码或关键词').fill('布局')
                page.get_by_role('textbox',name='输入股票名称、代码或关键词').press('Enter')
                page.locator('[data-testid="stPlotlyChart"]').wait_for(timeout=20000)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                chart=page.locator('[data-testid="stPlotlyChart"]').bounding_box()
                assert chart['x']>=0 and chart['x']+chart['width']<=width+1
                page.screenshot(path=str(output/f'chart-{width}.png'),full_page=True)
                page.get_by_role('combobox').first.click()
                page.get_by_role('option',name='我的',exact=True).click()
                page.get_by_role('combobox').nth(1).click()
                page.get_by_role('option',name='研究历史',exact=True).click()
                page.get_by_text('长报告布局测试（测试夹具）',exact=False).first.click()
                page.get_by_text('历史研究，不代表最新观点或最新行情。').wait_for()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/f'report-{width}.png'),full_page=True)
                results.append({'width':width,'login':True,'navigation':True,'portfolio_form':True,'settings':True,'fixture_chart':True,'fixture_long_report':True,'horizontal_overflow':False})
                page.close()
            browser.close()
        (output/'mobile-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(json.dumps(results,ensure_ascii=False))
    finally:
        process.terminate();process.wait(timeout=15);log.close()
if __name__=='__main__':main()

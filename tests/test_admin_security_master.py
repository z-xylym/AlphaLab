"""Admin UI contracts backed by real test PostgreSQL, never production data."""
import pandas as pd
import pytest
from sqlalchemy import delete, select, update
from streamlit.testing.v1 import AppTest

from alphalab import provider
from alphalab.config import UserError
from alphalab.data import MarketData, DataUnavailable, now
from alphalab.db import cache, public
from alphalab.market_diagnostics import PROBES
from alphalab.ui import admin_security_master


EXCHANGES = {
    'security_master_sh': ('证券代码', '证券简称', '600868', '测试沪市证券'),
    'stock_info_sz_name_code': ('A股代码', 'A股简称', '000001', '测试深市证券'),
    'stock_info_bj_name_code': ('证券代码', '证券简称', '920001', '测试北市证券'),
}


def official_fixture(name, **kwargs):
    code_key, name_key, code, label = EXCHANGES[name]
    return pd.DataFrame([{code_key: code, name_key: label}])


def open_admin(system, monkeypatch, ordinary=False):
    settings, _, admin, user = system
    monkeypatch.setenv('DATABASE_URL', settings.database_url)
    monkeypatch.setenv('APP_SECRET_KEY', settings.app_secret_key)
    app = AppTest.from_file('app.py')
    app.session_state['token'] = user.token if ordinary else admin.token
    app.run(timeout=20)
    app.radio(key='navigation').set_value('我的').run(timeout=20)
    if not ordinary:
        app.selectbox[0].select('管理后台').run(timeout=20)
    assert not app.exception
    return app


def rendered_text(app):
    return '\n'.join(str(item.value) for kind in
                     ('error', 'warning', 'info', 'success', 'caption', 'markdown')
                     for item in getattr(app, kind))


def test_admin_status_is_cache_only_and_exchange_probes_visible(system, monkeypatch):
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('Status must not fetch'))
    app = open_admin(system, monkeypatch)
    assert any(x.value == '基础证券名单' for x in app.subheader)
    assert any(x.label == '更新基础证券名单' for x in app.button)
    assert '是否已有缓存：否' in rendered_text(app)
    choices = next(x.options for x in app.selectbox if x.label == '选择单个公开接口')
    assert set(EXCHANGES) <= set(choices) <= set(PROBES)


def test_ordinary_user_has_no_admin_entry_or_refresh_and_direct_call_denied(system, monkeypatch):
    _, auth, _, user = system
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('Unauthorized request'))
    app = open_admin(system, monkeypatch, ordinary=True)
    assert '管理后台' not in app.selectbox[0].options
    assert not any(x.value == '基础证券名单' for x in app.subheader)
    assert not any(x.label == '更新基础证券名单' for x in app.button)
    with pytest.raises(UserError):
        admin_security_master(MarketData(auth.db), user)


def test_admin_refresh_persists_real_adapter_result_and_status_survives_rerun(system, monkeypatch):
    _, auth, admin, user = system
    admin.put('watchlist_items', 'unchanged', {'code': '600868', 'name': '私人记录'})
    user.put('user_preferences', 'profile', {'level': '进阶'})
    before = (admin.list('watchlist_items'), user.list('user_preferences'))
    seen = []
    def call(name, **kwargs):
        seen.append(name)
        return official_fixture(name, **kwargs)
    monkeypatch.setattr(provider, 'call', call)
    app = open_admin(system, monkeypatch)
    monkeypatch.setattr(MarketData, 'spot', lambda *a, **k: pytest.fail('Must not depend on snapshots'))
    next(x for x in app.button if x.label == '更新基础证券名单').click().run(timeout=20)
    assert not app.exception and not app.error
    assert sorted(seen) == sorted(set(EXCHANGES)-{'stock_info_bj_name_code'})
    message = next(x.value for x in app.success if '更新成功' in x.value)
    assert all(x in message for x in ('股票数量：2', '来源：', '数据时间', '交易所公开证券列表'))
    with auth.db.connect() as conn:
        cached = conn.execute(select(cache).where(cache.c.key.like('master:v1:%'))).mappings().all()
        master = conn.execute(select(public['stock_master'])).mappings().all()
    assert len(cached) == 2 and len(master) == 2
    assert all(x['payload']['price'] is None for x in master)
    assert before == (admin.list('watchlist_items'), user.list('user_preferences'))
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('Rerun must use cache'))
    app.run(timeout=20)
    assert not app.exception
    assert next(x.value for x in app.metric if x.label == '股票数量') == '2'
    status = app.dataframe[0].value
    assert set(status['交易所']) == {'SH', 'SZ'}
    assert not status['stale'].any()
    assert status['抓取时间'].str.len().min() > 10


@pytest.mark.parametrize('failure_layer', ['provider', 'management'])
def test_failed_admin_refresh_retains_cache_and_does_not_leak(system, monkeypatch, capsys, caplog, failure_layer):
    _, auth, _, _ = system
    data = MarketData(auth.db)
    monkeypatch.setattr(provider, 'call', official_fixture)
    data.security_master(refresh=True)
    with auth.db.begin() as conn:
        conn.execute(update(cache).where(cache.c.key.like('master:v1:%')).values(expires_at=now()))
    def stored():
        with auth.db.connect() as conn:
            return (conn.execute(select(cache)).mappings().all(),
                    conn.execute(select(public['stock_master'])).mappings().all())
    before = stored()
    sensitive = 'https://secret.invalid/?password=PRIVATE_PASSWORD headers=PRIVATE_HEADER cookie=PRIVATE_COOKIE body=PRIVATE_BODY 13999999999'
    def fail(*a, **k):
        raise RuntimeError(sensitive)
    monkeypatch.setattr(provider, 'call', fail)
    if failure_layer == 'management':
        original = MarketData.security_master
        def management(self, *args, **kwargs):
            if kwargs.get('refresh'):
                fail()
            return original(self, *args, **kwargs)
        monkeypatch.setattr(MarketData, 'security_master', management)
    app = open_admin(system, monkeypatch)
    next(x for x in app.button if x.label == '更新基础证券名单').click().run(timeout=20)
    assert not app.exception
    assert any('更新失败，已有旧缓存已保留' in x.value for x in app.error)
    assert not any('更新成功' in x.value for x in app.success)
    assert before == stored()
    assert app.dataframe[0].value['stale'].all()
    captured = capsys.readouterr()
    output = rendered_text(app) + captured.out + captured.err + caplog.text
    for marker in ('secret.invalid', 'PRIVATE_PASSWORD', 'PRIVATE_HEADER', 'PRIVATE_COOKIE', 'PRIVATE_BODY', '13999999999'):
        assert marker not in output


def test_failed_first_refresh_shows_fixed_error_without_inventing_master(system, monkeypatch):
    _, auth, _, _ = system
    def fail(*a, **k):
        raise RuntimeError('secret-provider-error')
    monkeypatch.setattr(provider, 'call', fail)
    app = open_admin(system, monkeypatch)
    next(x for x in app.button if x.label == '更新基础证券名单').click().run(timeout=20)
    assert not app.exception and app.error
    assert '是否已有缓存：否' in rendered_text(app)
    assert 'secret-provider-error' not in rendered_text(app)
    with auth.db.connect() as conn:
        assert not conn.execute(select(cache)).first()
        assert not conn.execute(select(public['stock_master'])).first()
    with pytest.raises(DataUnavailable):
        MarketData(auth.db).security_master(cached_only=True)


def test_partial_refresh_counts_only_new_records_and_keeps_old_source_times(system, monkeypatch):
    _, auth, _, _ = system
    data = MarketData(auth.db)
    monkeypatch.setattr(provider, 'call', official_fixture)
    original = data.security_master(refresh=True)
    old = {x['exchange']: x['fetched_at'] for x in original['items']}
    def partial(name, **kwargs):
        if name != 'security_master_sh':
            raise provider.ProviderError('NETWORK_ERROR')
        return official_fixture(name, **kwargs)
    monkeypatch.setattr(provider, 'call', partial)
    app = open_admin(system, monkeypatch)
    next(x for x in app.button if x.label == '更新基础证券名单').click().run(timeout=20)
    assert not app.exception and not app.error
    assert any('本次更新股票数量：1' in x.value for x in app.success)
    assert any('部分交易所更新失败' in x.value for x in app.warning)
    status = app.dataframe[0].value.set_index('交易所')
    assert not status.loc['SH', 'stale']
    for exchange in ('SZ', 'BJ'):
        assert bool(status.loc[exchange, 'stale']) == (exchange=='SZ')
        assert status.loc[exchange, '抓取时间'] == old[exchange]


def test_admin_status_reads_saved_stock_master_when_public_cache_absent(system, monkeypatch):
    _, auth, _, _ = system
    monkeypatch.setattr(provider, 'call', official_fixture)
    original = MarketData(auth.db).security_master(refresh=True)
    with auth.db.begin() as conn:
        conn.execute(delete(cache))
    monkeypatch.setattr(provider, 'call', lambda *a, **k: pytest.fail('Status must not fetch'))
    app = open_admin(system, monkeypatch)
    assert not app.exception
    assert next(x.value for x in app.metric if x.label == '股票数量') == '3'
    status = app.dataframe[0].value
    assert status['stale'].all()
    assert set(status['抓取时间']) == {x['fetched_at'] for x in original['items']}
    with auth.db.connect() as conn:
        assert not conn.execute(select(cache)).first()


def test_bj_refresh_is_separate_from_sh_sz_and_retains_timeout_diagnostic(system, monkeypatch):
    seen=[]
    def call(name, **kwargs):
        seen.append(name)
        return official_fixture(name, **kwargs)
    monkeypatch.setattr(provider, 'call', call)
    app=open_admin(system, monkeypatch)
    next(x for x in app.button if x.label=='更新基础证券名单').click().run(timeout=20)
    assert set(seen)=={'security_master_sh','stock_info_sz_name_code'}
    seen.clear()
    next(x for x in app.button if x.key=='admin_refresh_security_master_bj').click().run(timeout=20)
    assert seen==['stock_info_bj_name_code']
    assert not app.exception and not app.error
    assert any('股票数量：1' in x.value for x in app.success)
    assert set(app.dataframe[0].value['交易所'])=={'SH','SZ','BJ'}
    def timeout(*a, **k):raise provider.ProviderError('PROVIDER_TIMEOUT')
    monkeypatch.setattr(provider, 'call', timeout)
    next(x for x in app.button if x.key=='admin_refresh_security_master_bj').click().run(timeout=20)
    assert not app.exception
    assert any('更新失败' in x.value for x in app.error)
    status=app.dataframe[0].value.set_index('交易所')
    assert status.loc['BJ','stale']
    assert not status.loc['SH','stale'] and not status.loc['SZ','stale']

from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, text
from alphalab.config import Settings, SetupRequired
from alphalab.database_ca import CAConfigurationError
from alphalab.runtime_database import RuntimeEngines

URL='postgresql+psycopg://postgres.project:never-print-password@region.pooler.supabase.com:5432/postgres?sslmode=verify-full&sslrootcert=system'

@pytest.fixture
def ca(tmp_path):
    path=tmp_path/'official-test-ca.crt'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tmp_path/'test.key'),
                    '-out',str(path),'-subj','/CN=Runtime test CA','-days','2',
                    '-addext','basicConstraints=critical,CA:TRUE'],capture_output=True,check=True)
    return path

class FakeEngine:
    def __init__(self,url):
        self.url=make_url(url);self.path=Path(self.url.query['sslrootcert']);self.connects=0;self.disposes=0
    def connect(self):
        assert self.path.is_file()
        self.connects+=1
    def dispose(self):
        assert self.path.is_file(), 'Dispose must happen BEFORE CA release'
        self.disposes+=1

@pytest.fixture
def registry(tmp_path):
    def factory(url,**kwargs):
        assert kwargs['pool_pre_ping'] and kwargs['hide_parameters'] and kwargs['echo'] is False
        return FakeEngine(url)
    resource=RuntimeEngines(repository_ca=tmp_path/'repo-ca.crt',engine_factory=factory)
    yield resource
    resource.shutdown()


def test_rerun_dispose_and_reconnect_keep_secret_ca(registry,ca):
    pem=ca.read_text()
    engine=registry.get(URL,pem)
    assert engine.path.stat().st_mode & 0o777==0o600
    assert engine.url.query['sslmode']=='verify-full' and engine.path.read_text()==pem
    for _ in range(3):
        assert registry.get(URL,pem) is engine
        engine.connect();engine.dispose();engine.connect()
    path=engine.path
    registry.shutdown()
    assert not path.exists()
    with pytest.raises(SetupRequired):registry.get(URL,pem)


def test_repository_ca_precedence_and_owned_snapshot(registry,ca):
    Path(registry._repository_ca).write_bytes(ca.read_bytes())
    engine=registry.get(URL,'invalid secret must not override repository')
    assert engine.path!=Path(registry._repository_ca)
    assert engine.path.read_bytes()==ca.read_bytes()
    Path(registry._repository_ca).unlink()
    engine.dispose();engine.connect()  # Repository updates cannot remove the engine's snapshot.


def test_invalid_repository_cannot_fall_back_to_valid_secret(registry,ca):
    Path(registry._repository_ca).write_text('invalid CA')
    with pytest.raises(SetupRequired,match='数据库安全连接配置未完成'):
        registry.get(URL,ca.read_text())
    assert not registry._resources


@pytest.mark.parametrize('pem',[None,'','invalid PEM','-----BEGIN PRIVATE KEY-----\nnot-a-ca\n-----END PRIVATE KEY-----'])
def test_missing_or_invalid_ca_fails_closed(registry,pem,capsys):
    with pytest.raises(SetupRequired) as caught:registry.get(URL,pem)
    assert '数据库安全连接配置未完成' in str(caught.value)
    assert URL not in str(caught.value) and 'never-print-password' not in str(caught.value)
    assert not capsys.readouterr().out and not registry._resources


def test_new_config_does_not_evict_old_sessions_ca(registry,ca):
    first=registry.get(URL,ca.read_text())
    second=registry.get(URL.replace('/postgres?', '/other?'),ca.read_text())
    assert first is not second
    assert first.path.exists() and second.path.exists()
    first.dispose();first.connect()


def test_concurrent_reruns_share_one_resource(registry,ca):
    pem=ca.read_text()
    with ThreadPoolExecutor(max_workers=6) as pool:
        engines=list(pool.map(lambda _:registry.get(URL,pem),range(12)))
    assert all(engine is engines[0] for engine in engines)
    assert len(registry._resources)==1


def test_bootstrap_prepared_ca_url_is_supported(registry,ca):
    prepared=make_url(URL).update_query_dict({'sslrootcert':str(ca)}).render_as_string(hide_password=False)
    engine=registry.get(prepared,'')
    assert engine.path.read_bytes()==ca.read_bytes() and engine.path!=ca
    engine.connect()


def test_settings_reads_streamlit_secret_and_runtime_engine(registry,ca,monkeypatch):
    from alphalab import db, runtime_database
    monkeypatch.delenv('DATABASE_URL',raising=False)
    monkeypatch.delenv('SUPABASE_CA_CERT',raising=False)
    monkeypatch.delenv('APP_SECRET_KEY',raising=False)
    settings=Settings.load({'DATABASE_URL':URL,'SUPABASE_CA_CERT':ca.read_text(),'APP_SECRET_KEY':'k'*64})
    assert settings.supabase_ca_cert==ca.read_text()
    assert 'never-print-password' not in repr(settings) and ca.read_text() not in repr(settings)
    monkeypatch.setattr(runtime_database,'runtime_engines',registry)
    engine=db.engine(settings)
    assert engine.path.exists() and engine.url.query['sslrootcert']!='system'


def test_engine_factory_failure_is_safe_and_releases_ca(ca,tmp_path,capsys):
    paths=[]
    def fail(url,**kwargs):
        paths.append(Path(make_url(url).query['sslrootcert']))
        raise RuntimeError(url+ca.read_text())
    registry=RuntimeEngines(repository_ca=tmp_path/'absent',engine_factory=fail)
    with pytest.raises(SetupRequired) as caught:registry.get(URL,ca.read_text())
    assert 'never-print-password' not in str(caught.value)
    assert ca.read_text() not in str(caught.value) and not paths[0].exists()
    captured=capsys.readouterr();assert not captured.out+captured.err
    registry.shutdown()


def test_reconnect_actual_pool_retains_ca_snapshot(system,ca,tmp_path):
    settings,auth,a,b=system
    observed=[]
    def local_factory(prepared,**kwargs):
        path=Path(make_url(prepared).query['sslrootcert'])
        observed.append(path)
        # Existing local socket PostgreSQL exercises real pool replacement; TLS
        # verification itself remains covered by the real libpq TLS fixture.
        return create_engine(settings.database_url,**kwargs)
    registry=RuntimeEngines(repository_ca=tmp_path/'absent',engine_factory=local_factory)
    try:
        engine=registry.get(URL,ca.read_text())
        for _ in range(3):
            with engine.connect() as conn:assert conn.scalar(text('SELECT 1'))==1
            engine.dispose()
            assert observed[0].exists()
    finally:registry.shutdown()
    assert not observed[0].exists()


def test_streamlit_invalid_ca_is_safe(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from alphalab import runtime_database
    registry=RuntimeEngines(repository_ca=Path('/tmp/no-repository-ca-for-app-test'))
    monkeypatch.setattr(runtime_database,'runtime_engines',registry)
    monkeypatch.setenv('DATABASE_URL',URL)
    monkeypatch.setenv('APP_SECRET_KEY','k'*64)
    monkeypatch.setenv('SUPABASE_CA_CERT','invalid-secret-ca')
    try:
        app=AppTest.from_file('app.py').run(timeout=20)
        assert not app.exception
        assert any('数据库安全连接配置未完成' in x.value for x in app.warning)
        assert 'never-print-password' not in str([x.value for x in app.warning])
    finally:registry.shutdown()


def test_streamlit_connection_error_never_shows_driver_text(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from sqlalchemy.exc import OperationalError
    from alphalab import ui
    def fail(*args):raise OperationalError(URL,{},Exception('certificate verify failed never-print-password'))
    monkeypatch.setattr(ui,'Auth',fail)
    app=AppTest.from_file('app.py').run(timeout=20)
    assert not app.exception
    assert any('数据库安全连接配置未完成' in x.value for x in app.error)
    assert 'never-print-password' not in str([x.value for x in app.error])

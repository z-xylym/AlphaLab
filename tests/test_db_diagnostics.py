import errno
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from alphalab.db import users
from alphalab import db_diagnostics as d
from scripts import diagnose_database as cli

SECRET = 'never-log-this-password-or-phone-13800000000'
URL = 'postgresql+psycopg://postgres.project:' + SECRET + '@aws-region.pooler.supabase.com:5432/postgres?sslmode=verify-full&sslrootcert=system'

@pytest.mark.parametrize('message,state,category',[
    ('password authentication failed '+SECRET, None, 'AUTHENTICATION_ERROR'),
    ('Tenant or user not found '+SECRET, None, 'AUTHENTICATION_ERROR'),
    ('untranslated '+SECRET, '28P01', 'AUTHENTICATION_ERROR'),
    ('database "'+SECRET+'" does not exist', None, 'DATABASE_NOT_FOUND'),
    ('untranslated '+SECRET, '3D000', 'DATABASE_NOT_FOUND'),
    ('could not translate host name '+SECRET, None, 'DNS_ERROR'),
    ('connection timed out '+SECRET, None, 'NETWORK_ERROR'),
    ('Network is unreachable '+SECRET, None, 'NETWORK_ERROR'),
    ('certificate verify failed '+SECRET, None, 'TLS_CERTIFICATE_ERROR'),
    ('server certificate does not match host name '+SECRET, None, 'TLS_HOSTNAME_MISMATCH'),
    ('root certificate file "'+SECRET+'" does not exist', None, 'TLS_CONFIGURATION_ERROR'),
    ('unexpected error '+SECRET, None, 'OTHER_CONNECTION_ERROR'),
])
def test_wrapped_libpq_error_is_classified_without_disclosure(message,state,category):
    original=Exception(message)
    original.sqlstate=state
    exc=OperationalError('sensitive '+URL, {'secret':SECRET}, original)
    result=d.classify_error(exc)
    assert result.category==category
    assert SECRET not in str(result)+result.advice

@pytest.mark.parametrize('error,category',[
    (socket.gaierror('secret '+SECRET),'DNS_ERROR'),
    (OSError(errno.EHOSTUNREACH,SECRET),'NETWORK_ERROR'),
    (TimeoutError(SECRET),'NETWORK_ERROR'),
])
def test_typed_errors(error,category):
    assert d.classify_error(error).category==category

@pytest.mark.parametrize('url,category',[
    ('', 'CONFIGURATION_ERROR'),
    ('not a url '+SECRET, 'CONFIGURATION_ERROR'),
    (URL.replace('postgresql+psycopg','postgresql'), 'CONFIGURATION_ERROR'),
    (URL.replace(':5432/',':6543/'),'POOLER_CONFIGURATION_ERROR'),
    (URL.replace('postgres.project:','postgres:'),'POOLER_CONFIGURATION_ERROR'),
    (URL.replace('verify-full','require'),'TLS_CONFIGURATION_ERROR'),
    (URL.replace('sslrootcert=system','sslrootcert=/nonexistent/secret-ca'),'TLS_CONFIGURATION_ERROR'),
    (URL+'&host=other.example','CONFIGURATION_ERROR'),
])
def test_config_errors_do_not_open_network(url,category,monkeypatch):
    def forbidden(*a):raise AssertionError('Network must not run')
    monkeypatch.setattr(d,'resolve',forbidden)
    assert d.diagnose(url).category==category

@pytest.mark.parametrize('uri', [URL, URL.replace(':5432/', '/')])
@pytest.mark.parametrize('stage,category', [('dns','DNS_ERROR'),('tcp','NETWORK_ERROR'),('connect','AUTHENTICATION_ERROR')])
def test_preflight_and_connect_failures(stage,category,monkeypatch,uri):
    def resolve(*a):
        if stage=='dns':raise socket.gaierror(SECRET)
        return []
    def tcp(*a):
        if stage=='tcp':raise TimeoutError(SECRET)
    class FakeEngine:
        def connect(self):raise Exception('password authentication failed '+SECRET)
        def dispose(self):pass
    monkeypatch.setattr(d,'resolve',resolve);monkeypatch.setattr(d,'tcp_probe',tcp)
    assert d.diagnose(uri,engine_factory=lambda *a,**k:FakeEngine()).category==category

@pytest.mark.parametrize('result',[d.Diagnosis(k) for k in d.ADVICE])
def test_cli_prints_only_allowlisted_category_and_advice(result,monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL',URL)
    monkeypatch.setattr(cli,'diagnose',lambda value:result)
    assert cli.main()==(0 if result.ok else 1)
    output=capsys.readouterr()
    assert output.out=='DIAGNOSIS: '+result.category+'\n建议：'+result.advice+'\n'
    assert not output.err and SECRET not in output.out and URL not in output.out

def test_cli_unexpected_exception_is_redacted(monkeypatch,capsys):
    def fail(value):raise RuntimeError(URL+' '+SECRET)
    monkeypatch.setattr(cli,'diagnose',fail)
    assert cli.main()==1
    out=capsys.readouterr()
    assert 'OTHER_CONNECTION_ERROR' in out.out and SECRET not in out.out+out.err

def test_actual_postgres_diagnosis_is_read_only_and_handles_schema(system):
    settings,auth,a,b=system
    with auth.db.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS public.schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'))
        c.execute(text('INSERT INTO public.schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING'))
        before=c.execute(select(users)).mappings().all()
    observed=[]
    def factory(*a,**kwargs):
        assert kwargs['connect_args']=={'connect_timeout':10}
        assert kwargs['execution_options']=={'postgresql_readonly':True}
        e=d.create_engine(*a,**kwargs)
        @event.listens_for(e,'before_cursor_execute')
        def check(conn,cursor,statement,parameters,context,executemany):
            assert statement=='SELECT version FROM public.schema_migrations WHERE version=1'
            cursor.execute('SHOW transaction_read_only')
            observed.append(cursor.fetchone()[0])
        return e
    assert d.diagnose(settings.database_url,network_probe=False,engine_factory=factory).ok
    assert observed==['on']
    with auth.db.connect() as c:assert c.execute(select(users)).mappings().all()==before
    with auth.db.begin() as c:c.execute(text('DELETE FROM public.schema_migrations WHERE version=1'))
    try:
        assert d.diagnose(settings.database_url,network_probe=False).category=='SCHEMA_VERSION_ERROR'
    finally:
        with auth.db.begin() as c:c.execute(text('INSERT INTO public.schema_migrations(version) VALUES(1)'))

def test_workflow_diagnostic_has_no_admin_secrets():
    workflow=Path('.github/workflows/bootstrap-admin.yml').read_text()
    section=workflow.split('- name: Diagnose database connection (read only)')[1].split('- name: Check existing schema')[0]
    assert 'secrets.DATABASE_URL' in section
    assert 'ADMIN_' not in section and 'APP_SECRET_KEY' not in section
    assert "if: inputs.confirmation == 'INITIALIZE'" in workflow
    assert 'continue-on-error' not in workflow

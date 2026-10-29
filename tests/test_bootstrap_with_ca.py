from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import pytest
from sqlalchemy.engine import make_url
from alphalab.database_ca import CAConfigurationError, explicit_ca_url
from scripts import bootstrap_with_ca as wrapper

URL='postgresql+psycopg://postgres.project:test-private-password@aws-region.pooler.supabase.com:5432/postgres?sslmode=verify-full&sslrootcert=system'
PEM_SENTINEL='private-test-certificate-content'

@pytest.fixture
def prepared(monkeypatch,tmp_path):
    monkeypatch.setenv('DATABASE_URL',URL)
    monkeypatch.setenv('SUPABASE_CA_CERT',PEM_SENTINEL)
    monkeypatch.setenv('ADMIN_PHONE','13800000001')
    monkeypatch.setenv('ADMIN_INITIAL_PASSWORD','private-admin-password')
    path=tmp_path/'temporary-ca.crt'
    path.write_text(PEM_SENTINEL)
    state={'active':False,'contexts':0,'calls':[]}
    @contextmanager
    def context(value,**kwargs):
        assert value==URL and kwargs['certificate_secret']==PEM_SENTINEL
        state['active']=True;state['contexts']+=1
        try:yield make_url(value).update_query_dict({'sslrootcert':str(path)}).render_as_string(hide_password=False)
        finally:
            state['active']=False
            path.unlink()
    monkeypatch.setattr(wrapper,'explicit_ca_url',context)
    def run(args,**kwargs):
        assert state['active'] and path.exists()
        assert args[:3]==[sys.executable,'-m','scripts.manage']
        assert kwargs['capture_output'] and kwargs['timeout']==60
        assert 'SUPABASE_CA_CERT' not in kwargs['env']
        uri=make_url(kwargs['env']['DATABASE_URL'])
        assert uri.query['sslrootcert']==str(path) and uri.query['sslmode']=='verify-full'
        state['calls'].append((args[-1],kwargs['env']['DATABASE_URL']))
        return SimpleNamespace(returncode=0,stdout=wrapper.SAFE_OUTPUT[args[-1]][0]+'\n',stderr='suppressed '+URL)
    monkeypatch.setattr(wrapper.subprocess,'run',run)
    return state,path,run


def assert_redacted(captured):
    for value in (URL,'test-private-password','13800000001','private-admin-password',PEM_SENTINEL):
        assert value not in captured.out+captured.err
    assert not captured.err


def test_all_commands_share_one_ca_context_and_parent_url_unchanged(prepared,monkeypatch,capsys):
    import os
    state,path,_=prepared
    assert wrapper.main()==0
    assert state['contexts']==1
    assert [x[0] for x in state['calls']]==['check','bootstrap','admin-check']
    assert len({x[1] for x in state['calls']})==1
    assert not state['active'] and not path.exists()
    assert os.environ['DATABASE_URL']==URL and os.environ['SUPABASE_CA_CERT']==PEM_SENTINEL
    output=capsys.readouterr();assert_redacted(output)
    assert 'Admin created.' in output.out and 'completed with explicit CA' in output.out


@pytest.mark.parametrize('failed', ['check','bootstrap','admin-check'])
def test_child_failure_stops_chain_and_suppresses_raw_output(prepared,monkeypatch,capsys,failed):
    state,path,run=prepared
    def fail(args,**kwargs):
        result=run(args,**kwargs)
        if args[-1]==failed:return SimpleNamespace(returncode=1,stdout=URL,stderr=PEM_SENTINEL)
        return result
    monkeypatch.setattr(wrapper.subprocess,'run',fail)
    assert wrapper.main()==1 and not path.exists()
    assert [x[0] for x in state['calls']]==list(wrapper.COMMANDS[:wrapper.COMMANDS.index(failed)+1])
    output=capsys.readouterr();assert_redacted(output)
    assert 'MANAGEMENT_FAILED: '+failed in output.out


def test_invalid_ca_never_starts_management(monkeypatch,capsys):
    def invalid(*a,**k):raise CAConfigurationError(URL)
    def forbidden(*a,**k):pytest.fail('No child may execute with invalid CA')
    monkeypatch.setattr(wrapper,'explicit_ca_url',invalid)
    monkeypatch.setattr(wrapper.subprocess,'run',forbidden)
    assert wrapper.main()==1
    out=capsys.readouterr();assert_redacted(out)
    assert 'TLS_CA_CONFIGURATION_ERROR' in out.out


def test_existing_admin_preserved_message(prepared,monkeypatch,capsys):
    state,path,run=prepared
    def existing(args,**kwargs):
        result=run(args,**kwargs)
        if args[-1]=='bootstrap':result.stdout='Admin already exists; unchanged.\n'
        return result
    monkeypatch.setattr(wrapper.subprocess,'run',existing)
    assert wrapper.main()==0
    out=capsys.readouterr();assert_redacted(out)
    assert 'Admin already exists; unchanged.' in out.out


@pytest.mark.parametrize('kind',['timeout','unexpected-output'])
def test_exception_or_unknown_output_is_redacted_and_ca_removed(prepared,monkeypatch,capsys,kind):
    state,path,_=prepared
    def unexpected(*a,**k):
        if kind=='timeout':raise subprocess.TimeoutExpired(URL,60,output=PEM_SENTINEL)
        return SimpleNamespace(returncode=0,stdout=URL,stderr=PEM_SENTINEL)
    monkeypatch.setattr(wrapper.subprocess,'run',unexpected)
    assert wrapper.main()==1 and not path.exists()
    assert_redacted(capsys.readouterr())


def test_workflow_uses_ca_for_diagnosis_and_management():
    content=Path('.github/workflows/bootstrap-admin.yml').read_text()
    diagnosis=content.split('- name: Diagnose database connection (read only)')[1].split('- name: Check existing schema')[0]
    management=content.split('- name: Check existing schema and initialize administrator')[1]
    assert 'secrets.SUPABASE_CA_CERT' in diagnosis and '--explicit-ca' in diagnosis
    assert 'ADMIN_' not in diagnosis
    assert 'secrets.SUPABASE_CA_CERT' in management
    assert 'python -m scripts.bootstrap_with_ca' in management
    assert 'python -m scripts.manage ' not in management
    assert 'GITHUB_ENV' not in content and 'continue-on-error' not in content

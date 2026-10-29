"""Public certificates/private keys generated ONLY in temporary test directories."""
from pathlib import Path
import os
import socket
import subprocess
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from alphalab.database_ca import CAConfigurationError, explicit_ca_url, validate_ca
from alphalab.db_diagnostics import classify_error
from scripts import diagnose_database as cli

URL='postgresql+psycopg://postgres.project:never-log-password@aws-region.pooler.supabase.com:5432/postgres?sslmode=verify-full&sslrootcert=system'

def openssl(*args):
    subprocess.run(['openssl',*map(str,args)],check=True,capture_output=True)

@pytest.fixture(scope='module')
def certificates(tmp_path_factory):
    p=tmp_path_factory.mktemp('ssl-test-certificates')
    for name in ('ca','wrong-ca'):
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout',p/f'{name}.key',
                '-out',p/f'{name}.crt','-subj',f'/CN=Test fixture {name}', '-days','2',
                '-addext','basicConstraints=critical,CA:TRUE')
    openssl('req','-new','-newkey','rsa:2048','-nodes','-keyout',p/'server.key','-out',p/'server.csr','-subj','/CN=localhost')
    (p/'extensions').write_text('subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\n')
    openssl('x509','-req','-in',p/'server.csr','-CA',p/'ca.crt','-CAkey',p/'ca.key',
            '-CAcreateserial','-out',p/'server.crt','-days','2','-extfile',p/'extensions')
    (p/'server.key').chmod(0o600)
    return p

def test_repository_ca_only_changes_trust_path(certificates,tmp_path):
    with explicit_ca_url(URL,repository_ca=certificates/'ca.crt',temporary_root=tmp_path) as result:
        before,after=make_url(URL),make_url(result)
        assert before.set(query={})==after.set(query={})
        assert after.query==dict(before.query,sslrootcert=str(certificates/'ca.crt'))
        assert after.port==5432 and after.query['sslmode']=='verify-full'
    assert list(tmp_path.iterdir())==[]

def test_secret_file_is_private_and_deleted(certificates,tmp_path):
    with explicit_ca_url(URL,repository_ca=tmp_path/'absent',certificate_secret=(certificates/'ca.crt').read_text(),temporary_root=tmp_path) as result:
        path=Path(make_url(result).query['sslrootcert'])
        assert path.read_bytes()==(certificates/'ca.crt').read_bytes()
        assert path.stat().st_mode & 0o777==0o600
    assert not path.exists()

def test_temporary_ca_removed_after_connection_error(certificates,tmp_path):
    with pytest.raises(RuntimeError):
        with explicit_ca_url(URL,repository_ca=tmp_path/'absent',certificate_secret=(certificates/'ca.crt').read_text(),temporary_root=tmp_path) as result:
            path=Path(make_url(result).query['sslrootcert'])
            raise RuntimeError('fixture')
    assert not path.exists()

@pytest.mark.parametrize('kind',['missing','empty','corrupt','private-key','leaf'])
def test_invalid_ca_fails_closed(certificates,tmp_path,kind):
    path=tmp_path/'ca.crt'
    if kind!='missing':
        data={'empty':b'', 'corrupt':b'-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----',
              'private-key':(certificates/'ca.key').read_bytes(), 'leaf':(certificates/'server.crt').read_bytes()}[kind]
        path.write_bytes(data)
    with pytest.raises(CAConfigurationError):
        with explicit_ca_url(URL,repository_ca=path,temporary_root=tmp_path):pass

def test_invalid_repository_ca_cannot_fall_back_to_secret(certificates,tmp_path):
    path=tmp_path/'ca.crt';path.write_text('not a certificate')
    with pytest.raises(CAConfigurationError):
        with explicit_ca_url(URL,repository_ca=path,certificate_secret=(certificates/'ca.crt').read_text()):pass

@pytest.mark.parametrize('uri',[URL.replace('verify-full','require'),URL.replace(':5432/',':6543/'),
    URL.replace('aws-region.pooler.supabase.com','db.project.supabase.co'), URL+'&hostaddr=127.0.0.1'])
def test_endpoint_and_tls_are_not_weakened(certificates,uri):
    with pytest.raises(CAConfigurationError):
        with explicit_ca_url(uri,repository_ca=certificates/'ca.crt'):pass

def test_cli_explicit_ca_redaction(certificates,tmp_path,monkeypatch,capsys):
    from contextlib import contextmanager
    from alphalab.db_diagnostics import Diagnosis
    @contextmanager
    def prepared(value,**kwargs):
        assert value==URL
        with explicit_ca_url(value,repository_ca=certificates/'ca.crt',temporary_root=tmp_path) as url:yield url
    monkeypatch.setenv('DATABASE_URL',URL)
    monkeypatch.setattr(cli,'explicit_ca_url',prepared)
    seen=[]
    def connected(url):
        seen.append(make_url(url));return Diagnosis('CONNECTED')
    monkeypatch.setattr(cli,'diagnose',connected)
    assert cli.main(['--explicit-ca'])==0
    output=capsys.readouterr()
    assert 'CONNECTED' in output.out and not output.err
    for sensitive in (URL,'never-log-password',str(certificates),(certificates/'ca.crt').read_text()):
        assert sensitive not in output.out
    assert seen[0].query['sslrootcert']!='system'

def test_missing_ca_cli_only_prints_safe_category(monkeypatch,capsys):
    def missing(*a,**k):raise CAConfigurationError('never-log-password')
    monkeypatch.setattr(cli,'explicit_ca_url',missing)
    assert cli.main(['--explicit-ca'])==1
    output=capsys.readouterr()
    assert 'TLS_CA_CONFIGURATION_ERROR' in output.out and 'never-log-password' not in output.out+output.err

def test_dedicated_workflow_cannot_initialize():
    content=Path('.github/workflows/verify-supabase-ca.yml').read_text()
    assert '--explicit-ca' in content
    assert 'ADMIN_' not in content and 'APP_SECRET_KEY' not in content
    assert 'scripts.manage' not in content and 'INITIALIZE' not in content
    assert 'secrets.SUPABASE_CA_CERT' in content


def test_real_psycopg_chain_and_hostname_verification(certificates):
    """Real libpq/OpenSSL against a minimal PostgreSQL-wire TLS fixture (not a real DB)."""
    import ssl
    import struct
    import threading
    import psycopg
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificates/'server.crt'),str(certificates/'server.key'))
    listener=socket.socket()
    listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
    port=listener.getsockname()[1]
    unexpected=[]
    def exact(conn,size):
        data=b''
        while len(data)<size:
            chunk=conn.recv(size-len(data))
            if not chunk:raise EOFError()
            data+=chunk
        return data
    def message(kind,payload):
        return kind+struct.pack('!I',len(payload)+4)+payload
    def serve():
        try:
            for _ in range(3):
                raw,_=listener.accept();raw.settimeout(3)
                try:
                    request=exact(raw,8)
                    if request==struct.pack('!II',8,80877104):
                        raw.sendall(b'N');request=exact(raw,8)
                    assert request==struct.pack('!II',8,80877103)
                    raw.sendall(b'S')
                    with context.wrap_socket(raw,server_side=True) as encrypted:
                        length=struct.unpack('!I',exact(encrypted,4))[0]
                        exact(encrypted,length-4)
                        response=message(b'R',struct.pack('!I',0))
                        for key,value in [('server_version','17.6'),('client_encoding','UTF8'),('standard_conforming_strings','on')]:
                            response+=message(b'S',key.encode()+b'\0'+value.encode()+b'\0')
                        response+=message(b'K',struct.pack('!II',1,1))+message(b'Z',b'I')
                        encrypted.sendall(response)
                        encrypted.recv(5)  # Client closes without running any query.
                except (ssl.SSLError, EOFError):
                    pass  # Expected rejection when the client uses a wrong CA or hostname.
                finally:raw.close()
        except Exception as exc:unexpected.append(type(exc).__name__)
        finally:listener.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    try:
        for host,ca,expected in [('localhost','ca.crt',None),('localhost','wrong-ca.crt','TLS_CERTIFICATE_ERROR'),
                                 ('127.0.0.1','ca.crt','TLS_HOSTNAME_MISMATCH')]:
            url=make_url(f'postgresql+psycopg://postgres@{host}:{port}/postgres?sslmode=verify-full&sslrootcert={certificates/ca}')
            kwargs=url.translate_connect_args(username='user',database='dbname') | dict(url.query) | {'connect_timeout':3}
            if expected is None:
                with psycopg.connect(**kwargs) as connection:
                    assert connection.pgconn.ssl_in_use
            else:
                with pytest.raises(Exception) as caught:psycopg.connect(**kwargs)
                assert classify_error(caught.value).category==expected
    finally:thread.join(timeout=6)
    assert not thread.is_alive() and not unexpected

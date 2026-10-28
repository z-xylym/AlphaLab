import os
import secrets
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import delete
from alphalab.config import Settings
from alphalab.db import metadata, engine_for
from alphalab.auth import Auth
from alphalab.repository import Repository

@pytest.fixture(scope='session')
def pg_url():
    provided=os.environ.get('TEST_DATABASE_URL')
    if provided:
        yield provided
        return
    import pgserver
    server=pgserver.get_server(Path(tempfile.mkdtemp(prefix='alphalab-tests-')),cleanup_mode='delete')
    yield server.get_uri().replace('postgresql://','postgresql+psycopg://',1)

@pytest.fixture
def system(pg_url):
    settings=Settings(database_url=pg_url,app_secret_key=secrets.token_hex(32),
        admin_phone='13800000001',admin_initial_password='test-admin-password-strong',deepseek_api_key='test-not-real-key')
    db=engine_for(pg_url)
    metadata.create_all(db)
    with db.begin() as c:
        for t in reversed(metadata.sorted_tables):c.execute(delete(t))
    auth=Auth(settings);assert auth.bootstrap()
    admin_token=auth.login('13800000001','test-admin-password-strong')
    code=auth.invite(admin_token,'13800000002')
    auth.register('13800000002','test-user-password-strong',code)
    user_token=auth.login('13800000002','test-user-password-strong')
    return settings,auth,Repository(auth,admin_token),Repository(auth,user_token)

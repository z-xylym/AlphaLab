"""Exercise the SQL-Editor-to-one-time-CLI path on a disposable PostgreSQL schema."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
from dataclasses import replace
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from alphalab.auth import Auth, hasher
from alphalab.config import Settings
from alphalab.db import engine_for, users


def test_sql_editor_then_bootstrap_workflow_without_migrate(pg_url):
    base = engine_for(pg_url)
    schema = 'bootstrap_test_' + uuid.uuid4().hex
    with base.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(pg_url)
    url = url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    db = engine_for(url)
    password = 'test-only-bootstrap-password'
    settings = Settings(database_url=url, app_secret_key='a' * 64,
                        admin_phone='13800000007', admin_initial_password=password)
    env = os.environ.copy()
    env.update(DATABASE_URL=url, APP_SECRET_KEY=settings.app_secret_key,
               ADMIN_PHONE=settings.admin_phone, ADMIN_INITIAL_PASSWORD=password)
    def run(command, success=True):
        r = subprocess.run([sys.executable, '-m', 'scripts.manage', command],
                           env=env, capture_output=True, text=True)
        assert (r.returncode == 0) == success, r.stdout
        assert password not in r.stdout + r.stderr
        assert settings.admin_phone not in r.stdout + r.stderr
        assert url not in r.stdout + r.stderr
        return r.stdout
    try:
        # Execute the SAME full SQL the user ran; no metadata.create_all shortcut.
        raw = db.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            raw.driver_connection.execute(Path('database/migrations/001_initial.sql').read_text())
        finally:
            raw.close()
        assert 'v1 reachable' in run('check')
        run('admin-check', success=False)
        assert 'Admin created.' in run('bootstrap')
        assert 'Admin ready:' in run('admin-check')
        with db.connect() as c:
            before = c.execute(select(users)).mappings().one()
            assert c.scalar(text('SELECT version FROM schema_migrations')) == 1
            assert hasher.verify(before['password_hash'], password)
        assert 'already exists' in run('bootstrap')
        # Removing one-time credentials must not break idempotency or reset a password.
        assert Auth(replace(settings, admin_phone='', admin_initial_password='')).bootstrap() is False
        with db.connect() as c:
            after = c.execute(select(users)).mappings().one()
            assert after == before
        # check must still fail under optimized Python; assertions are not a schema check.
        with db.begin() as c:
            c.execute(text('DELETE FROM schema_migrations WHERE version=1'))
        optimized = subprocess.run([sys.executable, '-O', '-m', 'scripts.manage', 'check'],
                                   env=env, capture_output=True, text=True)
        assert optimized.returncode != 0
    finally:
        db.dispose()
        with base.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

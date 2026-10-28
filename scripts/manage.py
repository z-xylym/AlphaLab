"""Run from the repository: python -m scripts.manage migrate|bootstrap|check"""
import argparse
from sqlalchemy import text
from alphalab.config import Settings
from alphalab.db import engine, metadata, lock
from alphalab.auth import Auth

def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['migrate', 'bootstrap', 'check'])
    args = p.parse_args()
    try:
        import streamlit as st
        settings = Settings.load(st.secrets)
        db = engine(settings)
        if args.command == 'migrate':
            with db.begin() as c:
                lock(c, 'schema-migration')
                c.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'))
                if not c.scalar(text('SELECT version FROM schema_migrations WHERE version=1')):
                    metadata.create_all(c)
                    # Block Supabase browser API roles. This app uses its backend-only DB role.
                    for table in metadata.tables:
                        c.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
                    c.execute(text('INSERT INTO schema_migrations(version) VALUES (1)'))
            print('Database schema v1 ready; existing records preserved.')
        elif args.command == 'bootstrap':
            print('Admin created.' if Auth(settings).bootstrap() else 'Admin already exists; unchanged.')
        else:
            with db.connect() as c:
                assert c.scalar(text('SELECT version FROM schema_migrations WHERE version=1')) == 1
            print('Database schema v1 reachable.')
    except Exception as exc:
        print('Operation failed:', type(exc).__name__, 'Check configuration/database access; no secret values printed.')
        raise SystemExit(1) from None
if __name__ == '__main__':
    main()

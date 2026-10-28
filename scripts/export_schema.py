from sqlalchemy import create_mock_engine
from alphalab.db import metadata

def sql():
    result=['-- AlphaLab schema v1. Backend-only database role. No anonymous browser policies.',
            'BEGIN;', 'CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());']
    def emit(statement,*args,**kwargs):
        result.append(str(statement.compile(dialect=mock.dialect)).strip()+';')
    mock=create_mock_engine('postgresql+psycopg://',emit)
    metadata.create_all(mock)
    result.extend(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY;' for name in metadata.tables)
    result+=['INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;','COMMIT;']
    return '\n\n'.join(result)+'\n'
if __name__=='__main__':print(sql(),end='')

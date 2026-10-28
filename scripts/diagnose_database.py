"""Read-only CLI; receives DATABASE_URL only. Never prints exceptions or settings."""
import os
from alphalab.db_diagnostics import Diagnosis, diagnose

def main():
    try:
        result = diagnose(os.environ.get('DATABASE_URL', ''))
    except Exception:
        result = Diagnosis('OTHER_CONNECTION_ERROR')
    print('DIAGNOSIS: ' + result.category)
    print('建议：' + result.advice)
    return 0 if result.ok else 1

if __name__ == '__main__':
    raise SystemExit(main())

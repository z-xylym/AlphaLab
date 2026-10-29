"""Read-only CLI; receives DATABASE_URL and optional public CA PEM. Never prints exceptions or settings."""
import argparse
import os
from alphalab.database_ca import CAConfigurationError, explicit_ca_url
from alphalab.db_diagnostics import Diagnosis, diagnose

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--explicit-ca', action='store_true', help='Require repository/Secret Supabase CA; no system trust fallback')
    args = parser.parse_args([] if argv is None else argv)
    try:
        if args.explicit_ca:
            with explicit_ca_url(os.environ.get('DATABASE_URL', ''),
                                 certificate_secret=os.environ.get('SUPABASE_CA_CERT', ''),
                                 temporary_root=os.environ.get('RUNNER_TEMP')) as url:
                result = diagnose(url)
        else:
            result = diagnose(os.environ.get('DATABASE_URL', ''))
    except CAConfigurationError:
        result = Diagnosis('TLS_CA_CONFIGURATION_ERROR')
    except Exception:
        result = Diagnosis('OTHER_CONNECTION_ERROR')
    print('DIAGNOSIS: ' + result.category)
    print('建议：' + result.advice)
    return 0 if result.ok else 1

if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))

"""One-time management chain; explicit CA lives until all child commands finish."""
import os
import subprocess
import sys
from alphalab.database_ca import CAConfigurationError, explicit_ca_url

COMMANDS = ('check', 'bootstrap', 'admin-check')
SAFE_OUTPUT = {
    'check': ('Database schema v1 reachable.',),
    'bootstrap': ('Admin created.', 'Admin already exists; unchanged.'),
    'admin-check': ('Admin ready: enabled account with Argon2id password hash. No credentials displayed.',),
}


def main():
    try:
        with explicit_ca_url(os.environ.get('DATABASE_URL', ''),
                             certificate_secret=os.environ.get('SUPABASE_CA_CERT', ''),
                             temporary_root=os.environ.get('RUNNER_TEMP')) as database_url:
            child_env = os.environ.copy()
            child_env['DATABASE_URL'] = database_url
            child_env.pop('SUPABASE_CA_CERT', None)  # Children need only the private CA file path.
            for command in COMMANDS:
                # Capture, never forward raw child output or CalledProcessError repr.
                result = subprocess.run([sys.executable, '-m', 'scripts.manage', command],
                                        env=child_env, capture_output=True, text=True,
                                        timeout=60, check=False)
                if result.returncode != 0:
                    print('MANAGEMENT_FAILED: ' + command + '. Stopped; no subsequent commands executed. No secrets displayed.')
                    return 1
                messages = [line for line in SAFE_OUTPUT[command] if line in result.stdout.splitlines()]
                if len(messages) != 1:
                    print('MANAGEMENT_OUTPUT_UNEXPECTED: ' + command + '. Stopped; raw output suppressed.')
                    return 1
                print(messages[0])
    except CAConfigurationError:
        print('TLS_CA_CONFIGURATION_ERROR: Explicit Supabase CA unavailable or invalid. No management commands executed.')
        return 1
    except Exception:
        print('MANAGEMENT_ERROR: Stopped safely. Connection settings, certificate and child output suppressed.')
        return 1
    print('Bootstrap chain completed with explicit CA. Temporary certificate context closed.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

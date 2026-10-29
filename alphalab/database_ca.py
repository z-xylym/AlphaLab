"""Explicit PostgreSQL trust anchor. Never log certificates or connection settings."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import ssl
import tempfile
from sqlalchemy.engine import make_url

class CAConfigurationError(Exception):
    """Only callers' fixed safe messages may be displayed."""

REPOSITORY_CA = Path(__file__).resolve().parents[1] / 'certs' / 'supabase-ca.crt'
CERTIFICATE = re.compile(rb'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----')


def validate_ca(path):
    try:
        if not path.is_file() or path.stat().st_size > 256_000:
            raise ValueError()
        data = path.read_bytes()
        # Reject private keys, arbitrary appended data, empty files and corrupt PEM.
        if not CERTIFICATE.findall(data) or CERTIFICATE.sub(b'', data).strip():
            raise ValueError()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(path))
        if context.cert_store_stats()['x509_ca'] < 1:
            raise ValueError()
    except Exception:
        raise CAConfigurationError() from None


@contextmanager
def explicit_ca_url(database_url, *, certificate_secret='', repository_ca=REPOSITORY_CA, temporary_root=None):
    """Change ONLY sslrootcert in memory, preserving endpoint, credentials and verify-full.

    A repository CA is preferred. Secret PEM is an alternative, never an automatic
    fallback for an invalid repository CA. No certificate/URL is exported to Actions logs.
    """
    try:
        url = make_url(database_url)
        if (url.drivername != 'postgresql+psycopg' or not url.host or
            not url.host.endswith('.pooler.supabase.com') or url.port not in (None, 5432) or
            url.query.get('sslmode') != 'verify-full'):
            raise ValueError()
        if any(k in url.query for k in ('host', 'hostaddr', 'port', 'user', 'password', 'dbname', 'service', 'servicefile')):
            raise ValueError()
    except Exception:
        raise CAConfigurationError() from None
    repository_ca = Path(repository_ca)
    with tempfile.TemporaryDirectory(prefix='alphalab-ca-', dir=temporary_root) as directory:
        if repository_ca.exists():
            path = repository_ca.resolve()
        elif certificate_secret:
            path = Path(directory) / 'supabase-ca.crt'
            try:
                with path.open('x', encoding='ascii') as file:
                    os.chmod(path, 0o600)
                    file.write(certificate_secret)
            except Exception:
                raise CAConfigurationError() from None
        else:
            raise CAConfigurationError() from None
        validate_ca(path)
        query = dict(url.query)
        query['sslrootcert'] = str(path)
        yield url.set(query=query).render_as_string(hide_password=False)

"""Process-owned engines and trust files. No eviction while a pool may reconnect."""
import atexit
from contextlib import ExitStack
import hashlib
from threading import RLock
from sqlalchemy import create_engine
from .database_ca import REPOSITORY_CA, explicit_ca_url
from .config import SetupRequired, SAFE_CONFIGURATION_MESSAGE



class RuntimeEngines:
    """Keep each CA context through reruns, dispose/reconnect and config changes.

    No LRU eviction: an old engine may still be referenced by a session. Shutdown
    is for process termination ONLY, after requests have stopped, never a rerun.
    """
    def __init__(self, repository_ca=REPOSITORY_CA, engine_factory=create_engine):
        self._repository_ca = repository_ca
        self._engine_factory = engine_factory
        self._resources = {}
        self._lock = RLock()
        self._closed = False

    def get(self, database_url, certificate_secret):
        if not isinstance(database_url, str) or not isinstance(certificate_secret, str):
            raise SetupRequired(SAFE_CONFIGURATION_MESSAGE)
        key = hashlib.sha256((database_url + '\0' + certificate_secret).encode()).digest()
        with self._lock:
            if self._closed:
                raise SetupRequired(SAFE_CONFIGURATION_MESSAGE)
            if key in self._resources:
                return self._resources[key][0]
            stack = ExitStack()
            try:
                repository_ca = self._repository_ca
                # Management children may receive an already-prepared explicit CA URL.
                # Preserve repository > Secret > prepared explicit file precedence.
                from pathlib import Path
                from sqlalchemy.engine import make_url
                if not Path(repository_ca).exists() and not certificate_secret:
                    prepared = make_url(database_url).query.get('sslrootcert')
                    if isinstance(prepared, str) and prepared != 'system':
                        repository_ca = Path(prepared)
                url = stack.enter_context(explicit_ca_url(
                    database_url, certificate_secret=certificate_secret,
                    repository_ca=repository_ca, snapshot_repository=True))
                instance = self._engine_factory(
                    url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                    connect_args={'connect_timeout': 10}, hide_parameters=True, echo=False)
            except Exception:
                try:
                    stack.close()
                except Exception:
                    pass
                raise SetupRequired(SAFE_CONFIGURATION_MESSAGE) from None
            self._resources[key] = (instance, stack)
            return instance

    def shutdown(self):
        """Stop service first. Dispose idle pools before releasing their CA contexts."""
        with self._lock:
            self._closed = True
            resources = list(self._resources.values())
            self._resources.clear()
            for instance, stack in resources:
                try:
                    instance.dispose()
                except Exception:
                    pass
                finally:
                    try:
                        stack.close()
                    except Exception:
                        pass


runtime_engines = RuntimeEngines()
atexit.register(runtime_engines.shutdown)

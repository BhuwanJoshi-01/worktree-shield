"""What a variable name says about its value, and which literal values are plain hosts.

Shared by every collector, so ``DB_PORT`` means the same thing in a ``.env`` file and
in an npm script.
"""

from __future__ import annotations

import ipaddress

from worktree_shield.models import ResourceKind


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# A *_PORT with one of these words names a server the app connects to, not one it runs.
CLIENT_WORDS = _words(
    "DB DATABASE POSTGRES POSTGRESQL PG MYSQL MARIADB REDIS MONGO MONGODB RABBITMQ AMQP SMTP "
    "MAIL EMAIL ELASTICSEARCH ELASTIC OPENSEARCH KAFKA MEMCACHED MINIO S3 NATS CLICKHOUSE"
)
_PATH_WORDS = _words(
    "DIR DIRECTORY PATH ROOT FOLDER CACHE OUT OUTPUT OUTDIR STORAGE UPLOAD UPLOADS DATA LOG "
    "LOGS TMP TEMP TMPDIR FILE LOCATION"
)
# Read-only by nature: search paths, installations, certificates and configuration.
_SEARCH_PATHS = _words(
    "PATH PYTHONPATH NODE_PATH LD_LIBRARY_PATH DYLD_LIBRARY_PATH MANPATH CLASSPATH GOPATH "
    "PKG_CONFIG_PATH CDPATH"
)
_READ_ONLY_WORDS = _words("HOME CERT CERTS KEY CA SSL TLS CONFIG CONF ETC")


def port_variable(name: str) -> ResourceKind | None:
    """``LISTEN_PORT`` for ``PORT`` and ``API_PORT``, ``CLIENT_ENDPOINT`` for ``DB_PORT``
    and ``PGPORT``, ``None`` for a name that holds no port."""
    upper = name.upper()
    if upper == "PGPORT":
        return ResourceKind.CLIENT_ENDPOINT
    if upper != "PORT" and not upper.endswith("_PORT"):
        return None
    if CLIENT_WORDS.intersection(upper.split("_")):
        return ResourceKind.CLIENT_ENDPOINT
    return ResourceKind.LISTEN_PORT


def host_variable(port_name: str) -> str:
    """The host variable that goes with a port variable: ``API_PORT`` → ``API_HOST``."""
    upper = port_name.upper()
    return "PGHOST" if upper == "PGPORT" else upper.removesuffix("PORT") + "HOST"


def is_mutable_path_variable(name: str) -> bool:
    """Whether a variable that holds a path is likely written to (``UPLOAD_DIR``,
    ``CACHE_PATH``) rather than read (``PYTHONPATH``, ``JAVA_HOME``, ``SSL_CERT_FILE``)."""
    upper = name.upper()
    if upper in _SEARCH_PATHS:
        return False
    words = set(upper.split("_"))
    return bool(words & _PATH_WORDS) and not words & _READ_ONLY_WORDS


def port_number(text: str) -> int | None:
    """A port written as plain ASCII digits, 1 to 65535."""
    if not text.isascii() or not text.isdigit() or len(text) > 5:
        return None
    port = int(text)
    return port if 1 <= port <= 65535 else None


def literal_host(text: str) -> str | None:
    """A host name or address as written, lower-cased; ``None`` for anything else
    (references, spaces, non-ASCII names)."""
    value = text.strip().lower()
    try:
        return str(ipaddress.ip_address(value.strip("[]")))
    except ValueError:
        pass
    labels = value.split(".")
    if value.isascii() and all(label and label.replace("-", "").isalnum() for label in labels):
        return value
    return None

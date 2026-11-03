"""Database URLs reduced to what identifies the database: engine, server and name.

User names and passwords are dropped while parsing; they reach neither the result nor
an error message, and an error never repeats the URL. When the server cannot be found
with certainty (an unencoded ``/``, ``?`` or ``#`` in a password moves the apparent
host, a libpq host list, an unexpanded ``${DB_HOST}``) the URL is refused with
:class:`DatabaseURLError` instead of being guessed: a wrong host would report a
collision that is not there, or hide one that is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote

_SCHEME = re.compile(r"(?:jdbc:)?([A-Za-z][A-Za-z0-9+.-]*)://(.*)", re.S)
_ENGINES = {
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "redis": "redis",
    "rediss": "redis",
    "mongodb": "mongodb",
    "sqlite": "sqlite",
}
_DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306, "redis": 6379, "mongodb": 27017}
_REFERENCE = re.compile(r"\$(?:\{|[A-Za-z_])")
_BRACKETED = re.compile(r"\[([^\]]*)\](?::(.*))?")
_DIGITS = re.compile(r"[0-9]{1,5}")  # str.isdigit() also accepts "²", which int() refuses


class DatabaseURLError(ValueError):
    """A database URL whose server cannot be determined safely; never contains the URL."""


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    """A database without credentials. ``host`` is lower case, ``None`` for the local
    default or a Unix ``socket``; ``port`` is the engine's default when not given;
    ``database`` is ``None`` when the URL leaves it to the server (Postgres then uses
    the user name, which was dropped). For SQLite ``database`` is the file path."""

    engine: str
    host: str | None
    port: int | None
    database: str | None
    socket: str | None = None

    @property
    def key(self) -> str:
        """``db://postgres/localhost:5432/app_dev``: equal keys, same database."""
        if self.engine == "sqlite":
            return f"db://sqlite/{self.database}"
        if self.socket is not None:
            server = f"unix:{self.socket}"
        elif self.host is None:
            server = "local"
        elif ":" in self.host and "," not in self.host:
            server = f"[{self.host}]"
        else:
            server = self.host
        port = "" if self.port is None else f":{self.port}"
        database = self.database if self.database is not None else "?"
        return f"db://{self.engine}/{server}{port}/{database}"


def parse_database_url(value: str) -> DatabaseTarget | None:
    """The database ``value`` points to, or ``None`` when it is not a database URL.

    Raises :class:`DatabaseURLError` for a database URL that cannot be read safely.
    """
    match = _SCHEME.fullmatch(value.strip())
    if match is None:
        return None
    scheme, rest = match.group(1).lower(), match.group(2)
    engine = _ENGINES.get(scheme.split("+", 1)[0])
    if engine is None:
        return None
    if engine == "sqlite":
        return _sqlite(rest)
    if _REFERENCE.search(rest):
        raise DatabaseURLError("it refers to another variable, which is not expanded")
    end = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=len(rest))
    authority, tail = rest[:end], rest[end:]
    if "@" in tail:
        raise DatabaseURLError(
            "it has an @ after the host part, so an unencoded /, ? or # in the password "
            "may have moved the host; percent-encode the password"
        )
    hostport = authority.rsplit("@", 1)[-1]  # everything before the last @ is credentials
    path, _, query_part = tail.partition("#")[0].partition("?")
    query = parse_qs(query_part)
    database = unquote(path.lstrip("/")) or None
    if engine == "mongodb":
        return _mongodb(hostport, database, srv=scheme == "mongodb+srv")
    if "," in hostport:
        raise DatabaseURLError("it lists several hosts")
    host, port = _host_and_port(hostport, _DEFAULT_PORTS[engine])
    socket = None
    if engine == "postgres":
        host = _host(_first(query, "host", host))
        port = _port(_first(query, "port", None), port)
        database = _first(query, "dbname", database)
    if engine == "redis":
        database = _first(query, "db", database) or "0"
    if host is not None and host.startswith("/"):
        host, socket = None, host
    return DatabaseTarget(engine, host, port, database, socket)


def _sqlite(rest: str) -> DatabaseTarget | None:
    path = unquote(rest.partition("?")[0].removeprefix("/"))
    if not path or path == ":memory:":
        return None  # in memory: nothing on disk to share
    return DatabaseTarget("sqlite", None, None, path)


def _mongodb(hostport: str, database: str | None, *, srv: bool) -> DatabaseTarget:
    default = None if srv else _DEFAULT_PORTS["mongodb"]
    servers = [_host_and_port(part, default) for part in hostport.split(",")]
    if len(servers) == 1:
        host, port = servers[0]
        return DatabaseTarget("mongodb", host, port, database)
    names = sorted(f"{host}:{port}" if port is not None else f"{host}" for host, port in servers)
    return DatabaseTarget("mongodb", ",".join(names), None, database)


def _host_and_port(hostport: str, default: int | None) -> tuple[str | None, int | None]:
    bracketed = _BRACKETED.fullmatch(hostport)
    if bracketed is not None:
        host, port = bracketed.group(1), bracketed.group(2)
    else:
        host, _, port = hostport.partition(":")
    return _host(unquote(host)), _port(port or None, default)


def _host(name: str | None) -> str | None:
    """Host names are case-insensitive; a socket path (``/run/postgresql``) is not."""
    if not name:
        return None
    return name if name.startswith("/") else name.lower()


def _port(text: str | None, default: int | None) -> int | None:
    if text is None:
        return default
    if not _DIGITS.fullmatch(text) or not 1 <= int(text) <= 65535:
        raise DatabaseURLError("its port is not a number from 1 to 65535")
    return int(text)


def _first(query: dict[str, list[str]], name: str, default: str | None) -> str | None:
    values = query.get(name)
    return values[0] if values else default

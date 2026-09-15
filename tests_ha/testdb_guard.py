"""Fail-closed, test-only PostgreSQL target selection (no application imports)."""
import os
from sqlalchemy.engine import make_url

LOCAL = ("172.25.0.2", 5432, "poc", "stella_test_ha_integration")
CI_TARGET = ("postgres", 5432, "stalla", "stella_test")


def select_test_url(source, env):
    try:
        url = make_url(env.get("STELLA_TEST_DATABASE_URL", source))
        target = (url.host, url.port, url.username, url.database)
        if url.drivername not in ("postgresql", "postgresql+psycopg2") or url.query:
            raise ValueError
        if any(key.startswith("PG") for key in env):
            raise ValueError
        if "STELLA_TEST_DATABASE_URL" not in env:
            sources = {
                ("172.25.0.2", 5432, "poc", "stella_ha_integration"): LOCAL,
                ("postgres", 5432, "stalla", "stella"): CI_TARGET,
            }
            if target in sources:
                url = url.set(database=sources[target][3])
                target = (url.host, url.port, url.username, url.database)
        if target != LOCAL and not (target == CI_TARGET and env.get("CI") == "true"):
            raise ValueError
        return url
    except Exception:
        raise ValueError("Refusing unsafe test database configuration") from None


MARKER = "ha-integration-test-only"
IDENTITY_SQL = (
    "SELECT current_database(), current_user, host(inet_server_addr()), "
    "inet_server_port(), current_setting('stella.test_isolation', true)"
)


def verify_identity(row, url, address):
    if row is None or tuple(row) != (url.database, url.username, address, url.port, MARKER):
        raise ValueError("Refusing unexpected test database connection identity")


def build_test_engine(source, env=None, factory=None):
    import ipaddress
    import socket
    from sqlalchemy import create_engine, event
    env = os.environ if env is None else env
    url = select_test_url(source, env)
    address = url.host
    if url.host == "postgres":
        addresses = {item[4][0] for item in socket.getaddrinfo("postgres", 5432, type=socket.SOCK_STREAM)}
        if len(addresses) != 1:
            raise ValueError("Ambiguous test database address")
        address = addresses.pop()
        ip = ipaddress.ip_address(address)
        if not ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_link_local:
            raise ValueError("Unsafe test database address")
    engine = (factory or create_engine)(url, connect_args={
        "hostaddr": address,
        "options": "-c stella.test_isolation=" + MARKER,
    })

    def revalidate():
        if select_test_url(source, env) != url:
            raise ValueError("Changed test database configuration")

    @event.listens_for(engine, "do_connect")
    def before_connect(dialect, record, args, params):
        revalidate()

    @event.listens_for(engine, "checkout")
    def check_connection(dbapi_connection, record, proxy):
        revalidate()
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(IDENTITY_SQL)
            verify_identity(cursor.fetchone(), url, address)
        finally:
            cursor.close()
            dbapi_connection.rollback()

    engine._stella_test_identity = (url, address, revalidate)
    return engine


def guarded_metadata(engine, metadata, operation):
    """Validate on the SAME connection/transaction used for each DDL operation."""
    from sqlalchemy import text
    if operation not in ("create_all", "drop_all"):
        raise ValueError("Unsupported test database operation")
    url, address, revalidate = engine._stella_test_identity
    revalidate()
    with engine.begin() as connection:
        verify_identity(connection.execute(text(IDENTITY_SQL)).one(), url, address)
        getattr(metadata, operation)(bind=connection)

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool, text

from alembic import context

from app.config import settings
from app.database import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
import app.models

# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    
    connectable = engine_from_config(
        {"url": settings.database_url},
        prefix="",
        poolclass=pool.NullPool,
    )


    try:
        with connectable.connect() as connection:
            if connection.dialect.name == "postgresql":
                # A waiting migrator must read the version committed by its
                # predecessor, not a snapshot established before taking the lock.
                connection = connection.execution_options(isolation_level="READ COMMITTED")
                # Own ONE transaction, including role checks, lock, version read,
                # every revision's DDL and the version update. Any exception rolls
                # back everything and releases the xact lock; never downgrade.
                # Revisions must not commit or use autocommit-only DDL.
                with connection.begin():
                    recovery, readonly = connection.execute(text(
                        "SELECT pg_is_in_recovery(), current_setting('transaction_read_only')"
                    )).one()
                    if recovery or readonly != "off":
                        raise RuntimeError("Migrations require a writable PostgreSQL primary")
                    # Fixed, database-wide Stella migration namespace, shared by
                    # every instance. Never derive this from a host/process/schema.
                    connection.execute(text("SELECT pg_advisory_xact_lock(1937007980, 1)"))
                    context.configure(
                        connection=connection, target_metadata=target_metadata,
                        transactional_ddl=True, transaction_per_migration=False,
                    )
                    with context.begin_transaction():
                        context.run_migrations()
            else:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

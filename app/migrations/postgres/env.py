# migrations/postgres/env.py
# This is the brain of Alembic.
# It tells Alembic:
#   1. Which database to connect to (from settings)
#   2. Which models to look at (your SQLAlchemy Base)
#   3. How to run migrations (async, because FastAPI is async)
#
# You write this once and never touch it again.

import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# ── Import your settings and Base ──────────────────────────────────────────
# settings gives us the real DB URL from .env
from app.core.config import settings

# Base is the SQLAlchemy DeclarativeBase all your models inherit from.
# Importing Base automatically registers all models that have been imported.
from app.core.database import Base

# CRITICAL: Import every model here so Alembic can see them.
# If you add a new model and forget to import it here,
# Alembic won't detect it when auto-generating migrations.
from app.models.postgres.billing import (  # noqa: F401
    ChargeMaster,
    Billing,
    BillingChargeLine,
    InsuranceClaim,
    AuditLog,
)

# ── Alembic Config ─────────────────────────────────────────────────────────
config = context.config

# Override the sqlalchemy.url in alembic.ini with the real URL from .env
# This is why the alembic.ini URL is just a placeholder
config.set_main_option("sqlalchemy.url", settings.POSTGRES_URL)

# Set up logging from the alembic.ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata tells Alembic what your models look like.
# When you run `alembic revision --autogenerate`, Alembic compares
# this metadata against the actual database and generates the diff.
target_metadata = Base.metadata


# ── Offline migrations ─────────────────────────────────────────────────────
# "Offline" means generating SQL scripts without connecting to the DB.
# Useful for reviewing what changes will be made before running them.

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (what you actually use) ──────────────────────────────
# "Online" means connecting to the DB and running migrations live.
# This is what `alembic upgrade head` does.

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type=True tells Alembic to detect column TYPE changes too,
        # not just added/removed columns
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    We use async because our app uses async SQLAlchemy.
    Alembic itself is sync, so we bridge the two here.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # Don't pool connections during migrations
    )

    async with connectable.connect() as connection:
        # run_sync bridges async connection to sync Alembic internals
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
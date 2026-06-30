from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, create_engine

from alembic import context

import sys
import os

# Add the backend root (parent of alembic) to sys.path so we can import app
# This is needed because env.py runs from within alembic/, and app/ is a sibling
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.database import Base, DATABASE_URL  # noqa: E402
from app.models import DiscoveredServiceDB, ServiceHealthDB  # noqa: E402, F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    if DATABASE_URL.startswith("sqlite:///:memory:"):
        engine = create_engine(
            DATABASE_URL,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=pool.StaticPool,
        )
    else:
        engine = create_engine(DATABASE_URL, future=True)

    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=DATABASE_URL.startswith("sqlite://")
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

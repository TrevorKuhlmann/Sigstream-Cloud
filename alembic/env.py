from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, create_engine
from dotenv import load_dotenv

import os
import sys

# Setup path to load project modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()  # ✅ Load .env file

from database import Base  # declarative_base
import models  # ensure models are registered with Base

# Alembic Config object
config = context.config

# Setup loggers
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for 'autogenerate'
target_metadata = Base.metadata

# Get the DB URL from env
DATABASE_URL = os.getenv("DATABASE_URL")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_engine(DATABASE_URL, pool_pre_ping=True)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


# Choose mode based on CLI context
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

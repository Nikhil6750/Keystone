"""Alembic migration environment for Keystone's SQLAlchemy models.

Resolves the database URL the same way `app.database.session` does (via
`app.core.config.get_settings().database_url`, with the same
`postgres://` -> `postgresql://` normalization for Supabase-style URLs)
rather than a static `sqlalchemy.url` in `alembic.ini` -- so `alembic
upgrade`/`alembic revision --autogenerate` always target whatever database
the application itself would connect to (`KEYSTONE_DATABASE_URL`/
`DATABASE_URL`), never a separately-maintained, driftable URL.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.database.base import Base

# Import every ORM model module so its tables register on `Base.metadata`
# before Alembic compares it against the database -- mirrors
# `tests/conftest.py`'s own "import models before create_all/compare"
# discipline, and `app.database.init_db`'s `from app import models`.
from app.models import audit_event as _audit_event  # noqa: F401
from app.models import compensation_attempt as _compensation_attempt  # noqa: F401
from app.models import step_attempt as _step_attempt  # noqa: F401
from app.models import workflow as _workflow  # noqa: F401
from app.models import workflow_step as _workflow_step  # noqa: F401
from app.persistence import models as _persistence_models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


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
        url=_database_url(),
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
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

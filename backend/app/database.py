"""Database connection and session management."""
import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

DEFAULT_DB_DIALECT = "mysql"
DEFAULT_DB_DRIVER = "aiomysql"


def get_default_driver(dialect: str) -> str:
    """Return the preferred async-capable driver for a dialect."""
    if dialect == "mysql":
        return DEFAULT_DB_DRIVER
    if dialect == "dm":
        return "dmAsync"
    return ""


def get_default_port(dialect: str) -> str:
    """Return the default port for a dialect."""
    if dialect == "mysql":
        return "3306"
    if dialect == "dm":
        return "5236"
    return ""


def configure_dm_runtime() -> None:
    """Expose DM client DLLs for dmPython/dmAsync on Windows."""
    dm_home = os.getenv("DM_HOME", "").strip()
    if not dm_home or os.name != "nt":
        return

    candidate_dirs = [
        Path(dm_home) / "bin",
        Path(dm_home) / "drivers" / "dpi",
    ]

    for candidate in candidate_dirs:
        if candidate.exists():
            os.add_dll_directory(str(candidate))


def _env_flag(name: str) -> bool | None:
    """Parse a boolean-like environment variable when explicitly provided."""
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value}")


def build_database_url() -> str:
    """Build database URL from a full DSN or structured environment variables."""
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url:
        return configured_url

    dialect = os.getenv("DB_DIALECT", DEFAULT_DB_DIALECT).strip() or DEFAULT_DB_DIALECT
    driver = os.getenv(
        "DB_DRIVER",
        get_default_driver(dialect),
    ).strip()

    if dialect == "sqlite":
        drivername = f"{dialect}+{driver}" if driver else dialect
        database = os.getenv("DB_NAME", "./flood_monitoring.db")
        return URL.create(drivername=drivername, database=database).render_as_string(
            hide_password=False
        )

    drivername = f"{dialect}+{driver}" if driver else dialect
    port = os.getenv("DB_PORT", get_default_port(dialect)).strip()
    return URL.create(
        drivername=drivername,
        username=os.getenv("DB_USER", "flood_user"),
        password=os.getenv("DB_PASSWORD", "flood_monitoring_2025"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(port) if port else None,
        database=os.getenv("DB_NAME", "flood_monitoring"),
    ).render_as_string(hide_password=False)


def get_database_backend_name(database_url: str) -> str:
    """Return SQLAlchemy backend name such as mysql/sqlite/postgresql/oracle."""
    return make_url(database_url).get_backend_name()


def should_auto_create_schema(dialect: str) -> bool:
    """Control ORM-driven schema bootstrap.

    DM uses a hand-authored bootstrap script because ORM metadata still does not
    fully express the validated sequence/trigger setup.
    """
    configured = _env_flag("AUTO_CREATE_SCHEMA")
    if configured is not None:
        return configured
    return dialect != "dm"


DATABASE_URL = build_database_url()
DATABASE_DIALECT = get_database_backend_name(DATABASE_URL)

if DATABASE_DIALECT == "dm":
    configure_dm_runtime()

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    future=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db():
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

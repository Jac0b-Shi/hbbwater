"""Database connection and session management."""
import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

DEFAULT_DB_DIALECT = "mysql"
DEFAULT_DB_DRIVER = "aiomysql"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_NAME = "flood_monitoring"
DEFAULT_DB_USER = "flood_user"
DEFAULT_DB_PASSWORD = "flood_monitoring_2025"

CONTROL_DEFAULT_DB_DIALECT = "sqlite"
CONTROL_DEFAULT_DB_DRIVER = "aiosqlite"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent if BACKEND_ROOT.name == "backend" else BACKEND_ROOT
CONTROL_DEFAULT_DB_PATH = PROJECT_ROOT / "runtime" / "control.db"

for env_file, override in ((".env", False), (".env.local", True)):
    load_dotenv(PROJECT_ROOT / env_file, override=override)


ControlBase = declarative_base()
BusinessBase = declarative_base()
Base = BusinessBase


@dataclass(slots=True)
class DatabaseSettings:
    database_url: str = ""
    dialect: str = DEFAULT_DB_DIALECT
    driver: str = DEFAULT_DB_DRIVER
    host: str = DEFAULT_DB_HOST
    port: str = ""
    database: str = DEFAULT_DB_NAME
    username: str = DEFAULT_DB_USER
    password: str = DEFAULT_DB_PASSWORD
    service_name: str = ""
    dm_home: str = ""
    dm_svc_path: str = ""
    auto_create_schema: bool | None = None


def get_default_driver(dialect: str) -> str:
    """Return the preferred async-capable driver for a dialect."""
    if dialect == "mysql":
        return DEFAULT_DB_DRIVER
    if dialect == "dm":
        return "dmAsync"
    if dialect == "sqlite":
        return CONTROL_DEFAULT_DB_DRIVER
    return ""


def get_default_port(dialect: str) -> str:
    """Return the default port for a dialect."""
    if dialect == "mysql":
        return "3306"
    if dialect == "dm":
        return "5236"
    return ""


def _first_env(names: Iterable[str], default: str = "") -> str:
    for name in names:
        if name in os.environ:
            return (os.getenv(name) or "").strip()
    return default


def _prefixed_names(prefixes: Iterable[str], key: str) -> list[str]:
    return [f"{prefix}{key}" if prefix else key for prefix in prefixes]


def _parse_env_flag(names: Iterable[str]) -> bool | None:
    value = None
    for name in names:
        if name in os.environ:
            value = os.getenv(name)
            break
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value}")


def configure_dm_runtime(dm_home: str = "", dm_svc_path: str = "") -> None:
    """Expose DM client DLLs for dmPython/dmAsync and pass service config path through."""
    resolved_home = dm_home.strip() or os.getenv("DM_HOME", "").strip()
    resolved_svc_path = dm_svc_path.strip() or os.getenv("DM_SVC_PATH", "").strip()

    if resolved_home:
        os.environ["DM_HOME"] = resolved_home
    if resolved_svc_path:
        os.environ["DM_SVC_PATH"] = resolved_svc_path

    if not resolved_home or os.name != "nt":
        return

    candidate_dirs = [
        Path(resolved_home) / "bin",
        Path(resolved_home) / "drivers" / "dpi",
    ]

    for candidate in candidate_dirs:
        if candidate.exists():
            os.add_dll_directory(str(candidate))


def build_database_settings_from_env(
    prefixes: tuple[str, ...] = ("",),
    *,
    default_dialect: str = DEFAULT_DB_DIALECT,
    default_driver: str | None = None,
    default_host: str = DEFAULT_DB_HOST,
    default_database: str = DEFAULT_DB_NAME,
    default_user: str = DEFAULT_DB_USER,
    default_password: str = DEFAULT_DB_PASSWORD,
    default_port: str | None = None,
) -> DatabaseSettings:
    """Build structured database settings from one or more environment prefixes."""
    database_url = _first_env(_prefixed_names(prefixes, "DATABASE_URL"))
    dialect = _first_env(
        _prefixed_names(prefixes, "DB_DIALECT"),
        default=default_dialect,
    ) or default_dialect
    driver = _first_env(
        _prefixed_names(prefixes, "DB_DRIVER"),
        default=default_driver or get_default_driver(dialect),
    ).strip()
    return DatabaseSettings(
        database_url=database_url,
        dialect=dialect,
        driver=driver,
        host=_first_env(_prefixed_names(prefixes, "DB_HOST"), default=default_host),
        port=_first_env(
            _prefixed_names(prefixes, "DB_PORT"),
            default=default_port or get_default_port(dialect),
        ),
        database=_first_env(_prefixed_names(prefixes, "DB_NAME"), default=default_database),
        username=_first_env(_prefixed_names(prefixes, "DB_USER"), default=default_user),
        password=_first_env(_prefixed_names(prefixes, "DB_PASSWORD"), default=default_password),
        service_name=_first_env(_prefixed_names(prefixes, "DB_SERVICE_NAME")),
        dm_home=_first_env(_prefixed_names(prefixes, "DM_HOME")),
        dm_svc_path=_first_env(_prefixed_names(prefixes, "DM_SVC_PATH")),
        auto_create_schema=_parse_env_flag(_prefixed_names(prefixes, "AUTO_CREATE_SCHEMA")),
    )


def build_control_database_settings_from_env() -> DatabaseSettings:
    """Return the control-plane database settings."""
    return build_database_settings_from_env(
        prefixes=("CONTROL_",),
        default_dialect=CONTROL_DEFAULT_DB_DIALECT,
        default_driver=CONTROL_DEFAULT_DB_DRIVER,
        default_host="",
        default_database=str(CONTROL_DEFAULT_DB_PATH),
        default_user="",
        default_password="",
        default_port="",
    )


def build_business_database_settings_from_env() -> DatabaseSettings:
    """Return the bootstrap business database settings from env."""
    return build_database_settings_from_env(prefixes=("BUSINESS_", ""))


def render_database_url(settings: DatabaseSettings) -> str:
    """Render a SQLAlchemy URL from structured settings."""
    if settings.database_url:
        return settings.database_url

    dialect = settings.dialect.strip() or DEFAULT_DB_DIALECT
    driver = settings.driver.strip() or get_default_driver(dialect)
    drivername = f"{dialect}+{driver}" if driver else dialect

    if dialect == "sqlite":
        return URL.create(drivername=drivername, database=settings.database).render_as_string(
            hide_password=False
        )

    host = settings.host.strip() or DEFAULT_DB_HOST
    port = settings.port.strip()
    if dialect == "dm" and settings.service_name.strip():
        host = settings.service_name.strip()
        port = ""

    return URL.create(
        drivername=drivername,
        username=settings.username,
        password=settings.password,
        host=host,
        port=int(port) if port else None,
        database=settings.database,
    ).render_as_string(hide_password=False)


def build_database_url() -> str:
    """Backward-compatible single-prefix URL builder used by smoke tests."""
    return render_database_url(build_database_settings_from_env(prefixes=("",)))


def build_database_connect_args(dialect: str, *, dm_svc_path: str = "") -> dict[str, object]:
    """Build optional driver-specific SQLAlchemy connect args."""
    if dialect == "sqlite":
        return {"timeout": 30}

    if dialect != "dm":
        return {}

    resolved_svc_path = dm_svc_path.strip() or os.getenv("DM_SVC_PATH", "").strip()
    if not resolved_svc_path:
        return {}
    return {"dmsvc_path": resolved_svc_path}


def should_auto_create_schema(dialect: str, configured: bool | None = None) -> bool:
    """Control ORM-driven schema bootstrap."""
    if configured is None:
        configured = _parse_env_flag(("AUTO_CREATE_SCHEMA",))
    if configured is not None:
        return configured
    return dialect != "dm"


def get_database_backend_name(database_url: str) -> str:
    """Return SQLAlchemy backend name such as mysql/sqlite/postgresql/oracle."""
    return make_url(database_url).get_backend_name()


def _ensure_sqlite_parent(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database_path = parsed.database
    if not database_path or database_path == ":memory:":
        return
    path = Path(database_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _create_engine(settings: DatabaseSettings) -> tuple[AsyncEngine, str, str]:
    url = render_database_url(settings)
    _ensure_sqlite_parent(url)
    dialect = get_database_backend_name(url)
    if dialect == "dm":
        configure_dm_runtime(settings.dm_home, settings.dm_svc_path)

    engine = create_async_engine(
        url,
        echo=False,
        connect_args=build_database_connect_args(dialect, dm_svc_path=settings.dm_svc_path),
        poolclass=NullPool,
        future=True,
    )
    return engine, url, dialect


CONTROL_DATABASE_SETTINGS = build_control_database_settings_from_env()
CONTROL_DATABASE_URL = render_database_url(CONTROL_DATABASE_SETTINGS)
control_engine, _, CONTROL_DATABASE_DIALECT = _create_engine(CONTROL_DATABASE_SETTINGS)
ControlSessionLocal = async_sessionmaker(
    control_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

_business_settings = build_business_database_settings_from_env()
DATABASE_URL = render_database_url(_business_settings)
DATABASE_DIALECT = get_database_backend_name(DATABASE_URL)
_business_engine: AsyncEngine | None = None
_business_session_factory: async_sessionmaker[AsyncSession] | None = None
_business_runtime_error = ""
_business_runtime_lock = asyncio.Lock()


def get_current_business_settings() -> DatabaseSettings:
    """Return the currently active business database settings snapshot."""
    return DatabaseSettings(**asdict(_business_settings))


def get_current_business_dialect() -> str:
    """Return the current business database backend name."""
    if _business_engine is not None:
        return _business_engine.dialect.name
    return get_database_backend_name(render_database_url(_business_settings))


def get_business_runtime_state() -> dict[str, str | bool]:
    """Expose lightweight runtime state for admin endpoints."""
    return {
        "dialect": get_current_business_dialect(),
        "configured": _business_session_factory is not None,
        "database": _business_settings.database,
        "host": _business_settings.host,
        "service_name": _business_settings.service_name,
        "last_error": _business_runtime_error,
    }


async def _prepare_business_engine(settings: DatabaseSettings) -> tuple[AsyncEngine, str, str]:
    from app.services.schema import ensure_runtime_schema

    engine, url, dialect = _create_engine(settings)
    try:
        async with engine.begin() as conn:
            if should_auto_create_schema(dialect, configured=settings.auto_create_schema):
                await conn.run_sync(Base.metadata.create_all)
            await ensure_runtime_schema(conn, dialect)
    except Exception:
        await engine.dispose()
        raise

    return engine, url, dialect


async def activate_business_database(settings: DatabaseSettings) -> dict[str, str]:
    """Validate and activate the business database runtime."""
    global _business_engine, _business_session_factory, _business_settings, DATABASE_URL, DATABASE_DIALECT, _business_runtime_error

    new_engine, database_url, dialect = await _prepare_business_engine(settings)
    old_engine = _business_engine
    _business_engine = new_engine
    _business_session_factory = async_sessionmaker(
        new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    _business_settings = DatabaseSettings(**asdict(settings))
    DATABASE_URL = database_url
    DATABASE_DIALECT = dialect
    _business_runtime_error = ""

    if old_engine is not None:
        await old_engine.dispose()

    return {"database_url": database_url, "dialect": dialect}


async def test_business_database_settings(settings: DatabaseSettings) -> dict[str, str]:
    """Validate that the provided business database settings are usable."""
    engine, database_url, dialect = await _prepare_business_engine(settings)
    await engine.dispose()
    return {"database_url": database_url, "dialect": dialect}


async def ping_business_database() -> dict[str, str | bool | int | None]:
    """Run a lightweight query against the active business database."""
    await ensure_business_database_ready()
    if _business_engine is None:
        raise RuntimeError("Business database engine is not configured")

    async with _business_engine.connect() as conn:
        value = (await conn.execute(text("select 1"))).scalar()

    return {
        **get_business_runtime_state(),
        "ok": value == 1,
        "select_1": value,
    }


async def probe_business_database_path() -> dict[str, str | bool | int | None]:
    """Run representative business queries through the active session path."""
    from sqlalchemy import desc, func, select

    from app.models import Sensor, SensorReading

    await ensure_business_database_ready()
    if _business_session_factory is None:
        raise RuntimeError("Business database session factory is not configured")

    async with _business_session_factory() as session:
        sensor_count = await session.scalar(select(func.count()).select_from(Sensor))
        reading_count = await session.scalar(select(func.count()).select_from(SensorReading))
        latest_reading_id = await session.scalar(
            select(SensorReading.id).order_by(desc(SensorReading.created_at)).limit(1)
        )

    return {
        **get_business_runtime_state(),
        "ok": True,
        "sensor_count": sensor_count,
        "reading_count": reading_count,
        "latest_reading_id": latest_reading_id,
    }


async def dispose_databases() -> None:
    """Dispose all active SQLAlchemy engines."""
    if _business_engine is not None:
        await _business_engine.dispose()
    await control_engine.dispose()


async def ensure_business_database_ready() -> None:
    """Lazily initialize the business runtime without crashing control-plane requests."""
    global _business_runtime_error

    if _business_session_factory is not None:
        return

    async with _business_runtime_lock:
        if _business_session_factory is not None:
            return
        try:
            await activate_business_database(_business_settings)
        except Exception as exc:
            _business_runtime_error = str(exc)
            raise


async def get_control_db():
    """Dependency to get control-plane database session."""
    async with ControlSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_business_db():
    """Dependency to get business-plane database session."""
    try:
        await ensure_business_database_ready()
    except Exception as exc:
        detail = "业务数据库当前不可用，请先在系统设置中检查业务数据库配置"
        if _business_runtime_error:
            detail = f"{detail}: {_business_runtime_error}"
        raise HTTPException(status_code=503, detail=detail) from exc

    async with _business_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def business_session_scope():
    """Create a committed business database session outside FastAPI dependencies."""
    await ensure_business_database_ready()
    if _business_session_factory is None:
        raise RuntimeError("Business database session factory is not configured")

    async with _business_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


get_db = get_business_db

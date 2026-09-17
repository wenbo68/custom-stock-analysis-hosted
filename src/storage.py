# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 存储层
===================================

职责：
1. 管理 SQLite 数据库连接（单例模式）
2. 定义 ORM 数据模型
3. 提供数据存取接口
4. 实现智能更新逻辑（断点续传）
"""

import atexit
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, TypeVar

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    DateTime,
    Integer,
    UniqueConstraint,
    Text,
    text,
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import IntegrityError, OperationalError

from src.config import get_config

logger = logging.getLogger(__name__)
T = TypeVar("T")
CURRENT_SCHEMA_VERSION = "2026-06-05-create-all-baseline"

# SQLAlchemy ORM 基类
Base = declarative_base()


def utc_naive_now() -> datetime:
    """Return current UTC time without tzinfo for SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive_datetime(value: datetime) -> datetime:
    """Normalize aware datetimes to UTC-naive; treat naive values as UTC-naive."""
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# === 数据模型定义 ===

class DatabaseSchemaMigration(Base):
    """Applied database schema version marker."""

    __tablename__ = 'schema_migrations'

    version = Column(String(64), primary_key=True)
    description = Column(String(255), nullable=False)
    applied_at = Column(DateTime, default=datetime.now, nullable=False, index=True)


class TieredRunRecord(Base):
    """One tiered-analysis run (src/tiered_analysis): status + full report.

    The web tiered page lists these as its run history; result_json holds
    the serialized TierReport (dimensions, levels, badges) so revisiting a
    finished run needs no re-analysis.
    """

    __tablename__ = 'tiered_runs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, unique=True, index=True)
    stock_code = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default='running', index=True)
    result_json = Column(Text)
    #: The run's inputs (tier, capital, risk_fraction, reward_risk) as
    #: JSON, recorded at creation so history rows can show them while the
    #: run is still in flight (owner decision 2026-07-24).
    inputs_json = Column(Text)
    #: The signed-in user who started the run (public server); NULL on
    #: rows from before accounts existed, which no one can see.
    owner_user_id = Column(Integer, index=True)
    #: Run reuse (2026-09-17): the trading day the run analyses — the
    #: most recent completed session at creation, ISO "YYYY-MM-DD" — the
    #: main model that produced (or will produce) its outlook, and, on a
    #: run that borrowed another run's outlook, that run's task id.
    bar_date = Column(String(10), index=True)
    model = Column(String(128))
    source_task_id = Column(String(64), index=True)
    error = Column(Text)
    created_at = Column(DateTime, default=utc_naive_now, index=True)
    updated_at = Column(DateTime, default=utc_naive_now, onupdate=utc_naive_now, index=True)


class TieredRunTranscriptRecord(Base):
    """One LLM exchange of one tiered run (src/tiered_analysis/llm_support).

    A run's transcript is the list of its rows ordered by ``seq``: the
    pipeline stage, model, full prompt, raw reply, token counts, and the
    error when the call itself failed. Kept in its own table (not on the
    run row) so the history list stays light; rows older than
    ``history.TRANSCRIPT_MAX_AGE_DAYS`` are pruned at startup.
    """

    __tablename__ = 'tiered_run_transcripts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_naive_now, index=True)
    stage = Column(String(64))
    model = Column(String(128))
    temperature = Column(Float)
    duration_ms = Column(Integer)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    #: Which reply enforcement was requested: "schema", "json", or None.
    structured = Column(String(16))
    error = Column(Text)
    prompt = Column(Text)
    reply = Column(Text)


class UserRecord(Base):
    """A signed-in person (src/users.py): one row per provider account."""

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False)
    #: The provider's stable account id (never the email, which can change).
    provider_subject = Column(String(255), nullable=False)
    email = Column(String(255), index=True)
    display_name = Column(String(255))
    avatar_url = Column(Text)
    created_at = Column(DateTime, default=utc_naive_now, index=True)
    last_login_at = Column(DateTime, default=utc_naive_now)

    __table_args__ = (
        UniqueConstraint('provider', 'provider_subject', name='uix_user_provider_subject'),
    )


class UserSettingsRecord(Base):
    """A user's model choice and encrypted keys (src/user_settings.py)."""

    __tablename__ = 'user_settings'

    user_id = Column(Integer, primary_key=True)
    llm_model = Column(String(128))
    # The cheaper model for screening chores (news relevance); empty =
    # the main model does that work too.
    llm_sub_model = Column(String(128))
    llm_api_key_enc = Column(Text)
    finnhub_key_enc = Column(Text)
    alphavantage_key_enc = Column(Text)
    fred_key_enc = Column(Text)
    updated_at = Column(DateTime, default=utc_naive_now, onupdate=utc_naive_now)


class TieredCacheRecord(Base):
    """Fetched-data cache (src/tiered_analysis/cache_store): a JSON value
    per key. Safe to wipe — every row can be refetched from its vendor."""

    __tablename__ = 'tiered_cache'

    key = Column(String(255), primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utc_naive_now, onupdate=utc_naive_now, index=True)


class _DatabaseManagerMeta(type):
    """Serialize DatabaseManager construction across __new__ and __init__."""

    def __call__(cls, *args, **kwargs):
        with cls._init_lock:
            return super().__call__(*args, **kwargs)


class DatabaseManager(metaclass=_DatabaseManagerMeta):
    """
    数据库管理器 - 单例模式
    
    职责：
    1. 管理数据库连接池
    2. 提供 Session 上下文管理
    3. 封装数据存取操作
    """
    
    _instance: Optional['DatabaseManager'] = None
    _init_lock = threading.RLock()
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_url: Optional[str] = None):
        """
        初始化数据库管理器
        
        Args:
            db_url: 数据库连接 URL（可选，默认从配置读取）
        """
        if getattr(self, '_initialized', False):
            return

        created_engine = None

        try:
            config = get_config()
            if db_url is None:
                db_url = config.get_db_url()

            self._db_url = db_url
            self._sqlite_wal_enabled = config.sqlite_wal_enabled
            self._sqlite_busy_timeout_ms = config.sqlite_busy_timeout_ms

            engine_kwargs = {
                "echo": False,
                "pool_pre_ping": True,
            }
            if str(db_url).startswith("sqlite:") and self._sqlite_busy_timeout_ms > 0:
                engine_kwargs["connect_args"] = {
                    "timeout": self._sqlite_busy_timeout_ms / 1000,
                }

            # 创建数据库引擎
            created_engine = create_engine(
                db_url,
                **engine_kwargs,
            )
            self._engine = created_engine
            self._is_sqlite_engine = self._engine.url.get_backend_name() == 'sqlite'
            self._sqlite_file_db = self._is_sqlite_engine and self._is_file_sqlite_database()
            self._install_sqlite_pragma_handler()

            # 创建 Session 工厂
            self._SessionLocal = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
            )

            # 创建所有表
            Base.metadata.create_all(self._engine)
            self._ensure_column(TieredRunRecord.__tablename__, "inputs_json", "TEXT")
            self._ensure_column(TieredRunRecord.__tablename__, "owner_user_id", "INTEGER")
            self._ensure_column(TieredRunRecord.__tablename__, "bar_date", "VARCHAR(10)")
            self._ensure_column(TieredRunRecord.__tablename__, "model", "VARCHAR(128)")
            self._ensure_column(TieredRunRecord.__tablename__, "source_task_id", "VARCHAR(64)")
            self._ensure_column(UserSettingsRecord.__tablename__, "llm_sub_model", "VARCHAR(128)")
            self._ensure_schema_migration_record()

            self._initialized = True
            logger.info(f"数据库初始化完成: {db_url}")

            # 注册退出钩子，确保程序退出时关闭数据库连接
            atexit.register(DatabaseManager._cleanup_engine, self._engine)
        except Exception:
            self._initialized = False
            try:
                if created_engine is not None:
                    created_engine.dispose()
            except Exception as cleanup_exc:
                logger.warning("数据库初始化失败后的引擎清理也失败: %s", cleanup_exc)
            self._engine = None
            self._SessionLocal = None
            self.__class__._instance = None
            raise

    def _ensure_schema_migration_record(self) -> None:
        session = self._SessionLocal()
        values = {
            "version": CURRENT_SCHEMA_VERSION,
            "description": "Baseline schema created through SQLAlchemy metadata.create_all",
        }
        try:
            if self._is_sqlite_engine:
                statement = sqlite_insert(DatabaseSchemaMigration).values(**values)
                statement = statement.on_conflict_do_nothing(index_elements=["version"])
                session.execute(statement)
            else:
                session.execute(DatabaseSchemaMigration.__table__.insert().values(**values))
            session.commit()
        except IntegrityError:
            session.rollback()
            with self._SessionLocal() as verify_session:
                existing = verify_session.get(DatabaseSchemaMigration, CURRENT_SCHEMA_VERSION)
            if existing is None:
                raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _ensure_column(self, table: str, column: str, ddl_type: str) -> None:
        """Best-effort backfill of a column on databases created before it
        existed (create_all never alters existing tables). A failure only
        degrades the feature that reads the column, never startup."""
        try:
            existing = {
                col["name"] for col in inspect(self._engine).get_columns(table)
            }
            if column in existing:
                return
            with self._engine.begin() as connection:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
                )
        except Exception as exc:
            logger.warning("%s.%s backfill skipped: %s", table, column, exc)

    @classmethod
    def get_instance(cls) -> 'DatabaseManager':
        """获取单例实例"""
        with cls._init_lock:
            if cls._instance is None:
                cls()
            return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        with cls._init_lock:
            if cls._instance is not None:
                if hasattr(cls._instance, '_engine') and cls._instance._engine is not None:
                    cls._instance._engine.dispose()
                cls._instance._initialized = False
                cls._instance = None

    @classmethod
    def _cleanup_engine(cls, engine) -> None:
        """
        清理数据库引擎（atexit 钩子）

        确保程序退出时关闭所有数据库连接，避免 ResourceWarning

        Args:
            engine: SQLAlchemy 引擎对象
        """
        try:
            if engine is not None:
                engine.dispose()
                logger.debug("数据库引擎已清理")
        except Exception as e:
            logger.warning(f"清理数据库引擎时出错: {e}")

    def _install_sqlite_pragma_handler(self) -> None:
        """为 SQLite 连接安装竞争保护参数。"""
        if not self._is_sqlite_engine:
            return

        @event.listens_for(self._engine, "connect")
        def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={int(self._sqlite_busy_timeout_ms)}")
                if self._sqlite_file_db and self._sqlite_wal_enabled:
                    cursor.execute("PRAGMA journal_mode=WAL")
            except Exception as exc:
                logger.warning("初始化 SQLite PRAGMA 失败: %s", exc)
            finally:
                cursor.close()

    def _upsert_insert(self, model):
        """An INSERT that supports ``on_conflict_do_update`` on the
        engine in use — sqlite locally, Postgres on the public host."""
        return sqlite_insert(model) if self._is_sqlite_engine else pg_insert(model)

    def _is_file_sqlite_database(self) -> bool:
        database = (self._engine.url.database or "").strip()
        return bool(database) and database.lower() != ":memory:"

    @staticmethod
    def _is_sqlite_duplicate_column_error(exc: OperationalError, column: str) -> bool:
        err_text = str(getattr(exc, "orig", exc)).lower()
        return "duplicate column name" in err_text and column.lower() in err_text

    def get_session(self) -> Session:
        """
        获取数据库 Session
        
        使用示例:
            with db.get_session() as session:
                # 执行查询
                session.commit()  # 如果需要
        """
        if not getattr(self, '_initialized', False) or not hasattr(self, '_SessionLocal'):
            raise RuntimeError(
                "DatabaseManager 未正确初始化。"
                "请确保通过 DatabaseManager.get_instance() 获取实例。"
            )
        session = self._SessionLocal()
        try:
            return session
        except Exception:
            session.close()
            raise

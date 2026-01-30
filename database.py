"""
Database connection and session management.
Supports both SQLite (local) and PostgreSQL (production).
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from config import get_config

logger = logging.getLogger(__name__)

# Global engine and session factory
_engine = None
_async_session_factory = None


def _convert_database_url(url: str) -> str:
    """Convert database URL to async format."""
    # SQLite
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    # PostgreSQL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _is_sqlite(url: str) -> bool:
    """Check if URL is for SQLite database."""
    return "sqlite" in url.lower()


async def _ensure_table_columns(conn) -> None:
    """
    Best-effort schema migration for existing databases.

    We use SQLAlchemy's create_all() which does NOT add new columns to existing tables.
    This function adds missing columns that were introduced after initial deployment.
    """
    config = get_config()
    async_url = _convert_database_url(config.database.url)

    # Define required columns for each table
    messages_columns = {
        # column_name: ddl fragment (SQLite)
        "topic_summary": "topic_summary VARCHAR(100)",
        "warning_sent": "warning_sent BOOLEAN NOT NULL DEFAULT 0",
        "warning_sent_at": "warning_sent_at DATETIME",
    }

    user_preferences_columns = {
        "user_context": "user_context TEXT",
        "min_priority_score": "min_priority_score INTEGER NOT NULL DEFAULT 1",
        "warning_threshold_score": "warning_threshold_score INTEGER NOT NULL DEFAULT 8",
        "ignore_large_groups": "ignore_large_groups BOOLEAN NOT NULL DEFAULT 0",
        "max_group_size": "max_group_size INTEGER NOT NULL DEFAULT 20",
        "ignore_muted_chats": "ignore_muted_chats BOOLEAN NOT NULL DEFAULT 0",
    }

    # SQLite
    if _is_sqlite(async_url):
        # Migrate messages table
        result = await conn.exec_driver_sql("PRAGMA table_info(messages)")
        existing = {row[1] for row in result.fetchall()}  # row[1] = name

        for col, ddl in messages_columns.items():
            if col in existing:
                continue
            logger.warning(f"SQLite schema update: adding missing column messages.{col}")
            await conn.exec_driver_sql(f"ALTER TABLE messages ADD COLUMN {ddl}")

        # Migrate user_preferences table
        try:
            result = await conn.exec_driver_sql("PRAGMA table_info(user_preferences)")
            existing = {row[1] for row in result.fetchall()}

            for col, ddl in user_preferences_columns.items():
                if col in existing:
                    continue
                logger.warning(f"SQLite schema update: adding missing column user_preferences.{col}")
                await conn.exec_driver_sql(f"ALTER TABLE user_preferences ADD COLUMN {ddl}")
        except Exception as e:
            # Table might not exist yet
            logger.debug(f"user_preferences migration skipped: {e}")
        return

    # PostgreSQL (and other DBs that support information_schema + IF NOT EXISTS)
    try:
        # Migrate messages table
        result = await conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'messages' AND table_schema = 'public'"
        )
        existing = {row[0] for row in result.fetchall()}

        postgres_messages = {
            "topic_summary": "topic_summary VARCHAR(100)",
            "warning_sent": "warning_sent BOOLEAN NOT NULL DEFAULT FALSE",
            "warning_sent_at": "warning_sent_at TIMESTAMP",
        }
        for col, ddl in postgres_messages.items():
            if col in existing:
                continue
            logger.warning(f"Postgres schema update: adding missing column messages.{col}")
            await conn.exec_driver_sql(f"ALTER TABLE messages ADD COLUMN IF NOT EXISTS {ddl}")

        # Migrate user_preferences table
        result = await conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'user_preferences' AND table_schema = 'public'"
        )
        existing = {row[0] for row in result.fetchall()}

        postgres_preferences = {
            "user_context": "user_context TEXT",
            "min_priority_score": "min_priority_score INTEGER NOT NULL DEFAULT 1",
            "warning_threshold_score": "warning_threshold_score INTEGER NOT NULL DEFAULT 8",
            "ignore_large_groups": "ignore_large_groups BOOLEAN NOT NULL DEFAULT FALSE",
            "max_group_size": "max_group_size INTEGER NOT NULL DEFAULT 20",
            "ignore_muted_chats": "ignore_muted_chats BOOLEAN NOT NULL DEFAULT FALSE",
        }
        for col, ddl in postgres_preferences.items():
            if col in existing:
                continue
            logger.warning(f"Postgres schema update: adding missing column user_preferences.{col}")
            await conn.exec_driver_sql(f"ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS {ddl}")

    except Exception as e:
        # Don't fail startup if migration can't run; create_all already ran.
        logger.warning(f"Schema auto-migration skipped/failed: {e}")


async def init_database() -> None:
    """Initialize the database connection pool."""
    global _engine, _async_session_factory
    
    config = get_config()
    async_url = _convert_database_url(config.database.url)
    is_sqlite = _is_sqlite(async_url)
    
    # SQLite needs different settings
    if is_sqlite:
        _engine = create_async_engine(
            async_url,
            poolclass=StaticPool,  # Required for SQLite async
            echo=False,
            connect_args={"check_same_thread": False},
        )
    else:
        _engine = create_async_engine(
            async_url,
            poolclass=NullPool,  # Better for Railway's connection handling
            echo=False,
        )
    
    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    db_type = "SQLite" if is_sqlite else "PostgreSQL"
    logger.info(f"{db_type} database connection initialized")


async def close_database() -> None:
    """Close the database connection pool."""
    global _engine
    
    if _engine:
        await _engine.dispose()
        logger.info("Database connection pool closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.
    
    Usage:
        async with get_session() as session:
            result = await session.execute(query)
    """
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables defined in models."""
    from models import Base

    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure new columns exist for existing installations
        await _ensure_table_columns(conn)

    logger.info("Database tables created successfully")


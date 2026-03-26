from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.constants import DATABASE_STARTUP_PROBE_QUERY


@dataclass(slots=True)
class Database:
    """Container for async engine and session factory shared across the app."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


async def create_database(database_url: str) -> Database:
    """Create and validate database runtime objects for the process lifecycle."""

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )

    # Fail fast if database is unreachable at startup.
    async with engine.connect() as connection:
        await connection.execute(text(DATABASE_STARTUP_PROBE_QUERY))

    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    return Database(engine=engine, session_factory=session_factory)


async def dispose_database(database: Database | None) -> None:
    """Dispose DB engine gracefully when the process shuts down."""

    if database is None:
        return
    await database.engine.dispose()

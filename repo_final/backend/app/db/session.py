from __future__ import annotations
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from app.models.schemas import Base
from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_lightweight_migrations)


def _apply_lightweight_migrations(connection) -> None:
    """Apply additive development migrations to existing SQLite databases.

    ``create_all`` does not add columns to a table that already exists. This
    keeps local developer databases usable until the PostgreSQL/Alembic
    migration milestone in the architecture is introduced.
    """
    columns = {column["name"] for column in inspect(connection).get_columns("clips")}
    if "error_message" not in columns:
        connection.execute(text("ALTER TABLE clips ADD COLUMN error_message VARCHAR"))

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

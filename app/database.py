from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def normalize_database_url(database_url: str) -> str:
    normalized = str(database_url or "").strip()
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgres://")
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgresql://")
    return normalized


def validate_database_configuration(database_url: str, app_env: str) -> str:
    normalized = normalize_database_url(database_url)
    environment = str(app_env or "development").strip().lower()

    if not normalized:
        raise RuntimeError("DATABASE_URL is required")
    if not (normalized.startswith("sqlite://") or normalized.startswith("postgresql+")):
        raise RuntimeError("DATABASE_URL must use SQLite or PostgreSQL")
    if environment == "production" and normalized.startswith("sqlite://"):
        raise RuntimeError("Production requires PostgreSQL; SQLite is allowed only for local development")
    return normalized


def engine_options(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite://"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 30,
    }


def build_engine(database_url: str, app_env: str) -> Engine:
    validated_url = validate_database_configuration(database_url, app_env)
    return create_engine(validated_url, **engine_options(validated_url))


DATABASE_URL = validate_database_configuration(settings.database_url, settings.app_env)
engine = build_engine(DATABASE_URL, settings.app_env)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def check_database_connection(target_engine: Engine = engine) -> None:
    with target_engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def initialize_database(target_engine: Engine = engine) -> None:
    # Import models at runtime so every mapped table is registered before create_all.
    from app import models as _models  # noqa: F401

    check_database_connection(target_engine)
    Base.metadata.create_all(bind=target_engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

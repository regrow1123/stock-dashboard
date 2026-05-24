from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_url: str | None = None):
    from app.config import get_settings
    url = db_url or get_settings().db_url
    return create_engine(url, future=True, connect_args={"check_same_thread": False})


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _ensure_sqlite_columns(engine) -> None:
    # create_all won't ALTER existing tables; add missing columns by hand.
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(instruments)").fetchall()}
        if "sector" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE instruments ADD COLUMN sector VARCHAR")


def init_db(engine) -> None:
    # Import models so their tables are registered on Base.metadata
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)

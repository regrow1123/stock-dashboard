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


def init_db(engine) -> None:
    # Import models so their tables are registered on Base.metadata
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)

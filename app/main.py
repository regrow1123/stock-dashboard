from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import api
from app.db import init_db, make_engine, make_session_factory


def create_app(engine=None) -> FastAPI:
    eng = engine or make_engine()
    init_db(eng)
    SessionLocal = make_session_factory(eng)

    app = FastAPI(title="Stock Dashboard")

    def get_db():
        db: Session = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[api.get_db] = get_db
    app.include_router(api.router)

    static_dir = Path("web/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app

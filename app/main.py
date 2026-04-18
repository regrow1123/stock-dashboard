from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app import api
from app.db import init_db, make_engine, make_session_factory
from app.scheduler import make_scheduler


def create_app(engine=None, *, start_scheduler: bool = True) -> FastAPI:
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

    from app import telegram as tg
    app.include_router(tg.router)

    from app import views
    app.include_router(views.router)

    if start_scheduler:
        scheduler = make_scheduler(SessionLocal)

        @app.on_event("startup")
        def _start():
            scheduler.start()

        @app.on_event("shutdown")
        def _stop():
            scheduler.shutdown(wait=False)

    static_dir = Path("web/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith(("/static", "/accounts", "/")):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            return response

    app.add_middleware(NoCacheMiddleware)
    return app

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api import get_db
from app.models import Account

templates = Jinja2Templates(directory="web/templates")
router = APIRouter()

_ASSET_VER = str(int(time.time()))  # bumps every process start
_SW_PATH = Path("web/static/sw.js")


@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "asset_ver": _ASSET_VER,
            "page": "overview",
            "active_tab": "home",
            "back_href": None,
        },
    )


@router.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served at root so it can control the whole origin scope.
    # Browsers expect SW scripts to be revalidated frequently.
    if not _SW_PATH.exists():
        raise HTTPException(404)
    return FileResponse(
        _SW_PATH,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@router.get("/accounts/{account_id}", response_class=HTMLResponse)
def account_page(account_id: str, request: Request, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "account": {"id": acc.id, "name": acc.name,
                        "broker": acc.broker, "currency": acc.currency},
            "asset_ver": _ASSET_VER,
            "page": "account",
            "active_tab": "accounts",
            "back_href": "/",
            "back_label": "오버뷰로",
        },
    )

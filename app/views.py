from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api import get_db
from app.models import Account

templates = Jinja2Templates(directory="web/templates")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    return templates.TemplateResponse(request, "overview.html")


@router.get("/accounts/{account_id}", response_class=HTMLResponse)
def account_page(account_id: str, request: Request, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "account.html",
        {"account": {"id": acc.id, "name": acc.name,
                     "broker": acc.broker, "currency": acc.currency}},
    )

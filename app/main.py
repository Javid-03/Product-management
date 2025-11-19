import json
import math
import os
import tempfile
import uuid
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from .database import Base, SessionLocal, engine
from .models import Product, Webhook
from .tasks import import_products_task, redis_client

# create tables automatically for dev (use migrations in prod)
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

MAX_PER_PAGE = 200


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _sanitize_filters(
    page: int,
    per_page: int,
    filter_sku: Optional[str],
    filter_name: Optional[str],
    filter_description: Optional[str],
    filter_active: Optional[str],
) -> Dict:
    safe_page = max(page, 1)
    safe_per_page = min(max(per_page, 1), MAX_PER_PAGE)
    active_value = (filter_active or "all").lower()
    if active_value not in {"all", "active", "inactive"}:
        active_value = "all"
    return {
        "page": safe_page,
        "per_page": safe_per_page,
        "filter_sku": (filter_sku or "").strip(),
        "filter_name": (filter_name or "").strip(),
        "filter_description": (filter_description or "").strip(),
        "filter_active": active_value,
    }


def _parse_price(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        cents = int(Decimal(cleaned) * 100)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Price must be a valid number")
    if cents < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    return cents


def _parse_bool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes", "on"}


def _fetch_products(session, filters: Dict):
    offset = (filters["page"] - 1) * filters["per_page"]
    conditions = []
    if filters["filter_sku"]:
        conditions.append(Product.sku.ilike(f"%{filters['filter_sku']}%"))
    if filters["filter_name"]:
        conditions.append(Product.name.ilike(f"%{filters['filter_name']}%"))
    if filters["filter_description"]:
        conditions.append(Product.description.ilike(f"%{filters['filter_description']}%"))
    if filters["filter_active"] == "active":
        conditions.append(Product.active.is_(True))
    elif filters["filter_active"] == "inactive":
        conditions.append(Product.active.is_(False))

    base_stmt = select(Product)
    if conditions:
        base_stmt = base_stmt.where(*conditions)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_count = session.scalar(count_stmt) or 0
    pages = max(math.ceil(total_count / filters["per_page"]), 1) if total_count else 1
    if filters["page"] > pages:
        filters["page"] = pages
        offset = (filters["page"] - 1) * filters["per_page"]

    items_stmt = (
        base_stmt.order_by(Product.created_at.desc())
        .offset(offset)
        .limit(filters["per_page"])
    )
    products = session.execute(items_stmt).scalars().all()
    return {
        "products": products,
        "total": total_count,
        "pages": pages,
        "page": filters["page"],
    }


def _render_products_fragment(request: Request, session, filters: Dict) -> HTMLResponse:
    data = _fetch_products(session, filters)
    context = {
        "request": request,
        "products": data["products"],
        "page": data["page"],
        "pages": data["pages"],
        "total": data["total"],
        "filters": filters,
    }
    return templates.TemplateResponse("products_fragment.html", context)


def _render_webhooks_fragment(request: Request, session) -> HTMLResponse:
    items = session.execute(select(Webhook).order_by(Webhook.created_at.desc())).scalars().all()
    return templates.TemplateResponse(
        "webhooks_fragment.html",
        {"request": request, "webhooks": items},
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    temp_file = f"{tempfile.gettempdir()}/{uuid.uuid4()}.csv"
    with open(temp_file, "wb") as f:
        f.write(await file.read())

    task = import_products_task.delay(temp_file)
    return {"task_id": task.id}


@app.get("/task-status/{task_id}", response_class=JSONResponse)
def task_status(task_id: str):
    def _int_value(key: str) -> int:
        try:
            return int(redis_client.get(f"task:{task_id}:{key}") or 0)
        except (TypeError, ValueError):
            return 0

    processed = _int_value("progress")
    total = _int_value("total")
    invalid = _int_value("invalid")
    status = redis_client.get(f"task:{task_id}:status") or ""
    error = redis_client.get(f"task:{task_id}:error")
    percent = round((processed / total) * 100, 2) if total else None
    return {
        "task_id": task_id,
        "processed": processed,
        "total": total,
        "percent": percent,
        "status": status,
        "invalid": invalid,
        "error": error,
    }


@app.get("/products-fragment", response_class=HTMLResponse)
def products_fragment(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=MAX_PER_PAGE),
    filter_sku: str = "",
    filter_name: str = "",
    filter_description: str = "",
    filter_active: str = "all",
):
    filters = _sanitize_filters(page, per_page, filter_sku, filter_name, filter_description, filter_active)
    with SessionLocal() as session:
        return _render_products_fragment(request, session, filters)


def _product_action_response(request: Request, session, filters: Dict, payload: Dict):
    if _is_htmx(request):
        return _render_products_fragment(request, session, filters)
    return JSONResponse(payload)


@app.post("/product/create")
def create_product(
    request: Request,
    sku: str = Form(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    active: Optional[str] = Form("true"),
    page: int = Form(1),
    per_page: int = Form(20),
    filter_sku: Optional[str] = Form(None),
    filter_name: Optional[str] = Form(None),
    filter_description: Optional[str] = Form(None),
    filter_active: Optional[str] = Form(None),
):
    filters = _sanitize_filters(page, per_page, filter_sku, filter_name, filter_description, filter_active)
    sku_value = (sku or "").strip()
    if not sku_value:
        raise HTTPException(status_code=400, detail="SKU is required")
    with SessionLocal() as session:
        existing = session.execute(
            select(Product).where(func.lower(Product.sku) == sku_value.lower())
        ).scalars().first()
        price_cents = _parse_price(price)
        active_value = _parse_bool(active, True)
        payload = {"result": "created"}
        if existing:
            existing.name = name.strip() if name else None
            existing.description = description.strip() if description else None
            existing.price_cents = price_cents
            existing.active = active_value
            session.add(existing)
            payload = {"result": "updated", "id": existing.id}
        else:
            product = Product(
                sku=sku_value,
                name=name.strip() if name else None,
                description=description.strip() if description else None,
                price_cents=price_cents,
                active=active_value,
            )
            session.add(product)
            session.flush()
            payload = {"result": "created", "id": product.id}
        session.commit()
        return _product_action_response(request, session, filters, payload)


@app.post("/product/{product_id}/update")
def update_product(
    product_id: int,
    request: Request,
    sku: str = Form(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    active: Optional[str] = Form("true"),
    page: int = Form(1),
    per_page: int = Form(20),
    filter_sku: Optional[str] = Form(None),
    filter_name: Optional[str] = Form(None),
    filter_description: Optional[str] = Form(None),
    filter_active: Optional[str] = Form(None),
):
    filters = _sanitize_filters(page, per_page, filter_sku, filter_name, filter_description, filter_active)
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        sku_value = sku.strip()
        conflict = session.execute(
            select(Product).where(
                func.lower(Product.sku) == sku_value.lower(),
                Product.id != product_id,
            )
        ).scalars().first()
        if conflict:
            raise HTTPException(status_code=400, detail="SKU already exists")
        product.sku = sku_value
        product.name = name.strip() if name else None
        product.description = description.strip() if description else None
        product.price_cents = _parse_price(price)
        product.active = _parse_bool(active, product.active)
        session.add(product)
        session.commit()
        return _product_action_response(request, session, filters, {"result": "updated", "id": product_id})


@app.post("/product/{product_id}/delete")
def delete_product(
    product_id: int,
    request: Request,
    page: int = Form(1),
    per_page: int = Form(20),
    filter_sku: Optional[str] = Form(None),
    filter_name: Optional[str] = Form(None),
    filter_description: Optional[str] = Form(None),
    filter_active: Optional[str] = Form(None),
):
    filters = _sanitize_filters(page, per_page, filter_sku, filter_name, filter_description, filter_active)
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        session.delete(product)
        session.commit()
        return _product_action_response(request, session, filters, {"result": "deleted", "id": product_id})


@app.post("/products/delete-all")
def delete_all_products(
    request: Request,
    confirm: Optional[str] = Form(None),
    page: int = Form(1),
    per_page: int = Form(20),
    filter_sku: Optional[str] = Form(None),
    filter_name: Optional[str] = Form(None),
    filter_description: Optional[str] = Form(None),
    filter_active: Optional[str] = Form(None),
):
    if not _parse_bool(confirm, False):
        raise HTTPException(status_code=400, detail="Confirmation required")
    filters = _sanitize_filters(page, per_page, filter_sku, filter_name, filter_description, filter_active)
    with SessionLocal() as session:
        session.execute(Product.__table__.delete())
        session.commit()
        return _product_action_response(request, session, filters, {"deleted": True})


@app.get("/webhooks-fragment", response_class=HTMLResponse)
def webhooks_fragment(request: Request):
    with SessionLocal() as session:
        return _render_webhooks_fragment(request, session)


@app.post("/webhooks/create")
def create_webhook(
    request: Request,
    url: str = Form(...),
    event: str = Form(...),
    enabled: Optional[str] = Form("true"),
):
    with SessionLocal() as session:
        webhook = Webhook(
            url=url.strip(),
            event=event.strip(),
            enabled=_parse_bool(enabled, True),
        )
        session.add(webhook)
        session.commit()
        if _is_htmx(request):
            return _render_webhooks_fragment(request, session)
        return JSONResponse({"id": webhook.id})


@app.post("/webhooks/{webhook_id}/update")
def update_webhook(
    webhook_id: int,
    request: Request,
    url: str = Form(...),
    event: str = Form(...),
    enabled: Optional[str] = Form("true"),
):
    with SessionLocal() as session:
        webhook = session.get(Webhook, webhook_id)
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")
        webhook.url = url.strip()
        webhook.event = event.strip()
        webhook.enabled = _parse_bool(enabled, webhook.enabled)
        session.add(webhook)
        session.commit()
        if _is_htmx(request):
            return _render_webhooks_fragment(request, session)
        return JSONResponse({"id": webhook.id, "updated": True})


@app.post("/webhooks/{webhook_id}/delete")
def delete_webhook(webhook_id: int, request: Request):
    with SessionLocal() as session:
        webhook = session.get(Webhook, webhook_id)
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")
        session.delete(webhook)
        session.commit()
        if _is_htmx(request):
            return _render_webhooks_fragment(request, session)
        return JSONResponse({"deleted": True})


@app.post("/webhooks/test/{webhook_id}")
def test_webhook(webhook_id: int, request: Request):
    with SessionLocal() as session:
        webhook = session.get(Webhook, webhook_id)
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")
        payload = {}
        data = json.dumps({"test": True, "event": webhook.event}).encode("utf-8")
        req = urllib_request.Request(
            webhook.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=5) as resp:
                payload["status_code"] = resp.getcode()
                payload["text"] = resp.read(200).decode("utf-8", errors="ignore")
        except urllib_error.HTTPError as exc:
            payload["status_code"] = exc.code
            payload["text"] = exc.read(200).decode("utf-8", errors="ignore")
        except Exception as exc:
            message = str(exc)
            if _is_htmx(request):
                return HTMLResponse(f"<span class='error'>{message}</span>", status_code=500)
            return JSONResponse({"error": message}, status_code=500)

    if _is_htmx(request):
        return HTMLResponse(f"<span class='success'>Response {payload.get('status_code', '?')}</span>")
    return JSONResponse(payload)

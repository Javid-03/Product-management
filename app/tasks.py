import csv
import os
from decimal import Decimal
from typing import Dict, Optional, List

import redis

from .celery_app import celery
from .crud import upsert_products_bulk

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)


def _task_key(task_id: str, suffix: str) -> str:
    return f"task:{task_id}:{suffix}"


def _set_task_state(task_id: str, **state) -> None:
    for key, value in state.items():
        redis_client.set(_task_key(task_id, key), value)


def _count_rows(file_path: str) -> int:
    with open(file_path, "r", encoding="utf-8") as fh:
        total_lines = sum(1 for _ in fh)
    return max(total_lines - 1, 0)


def _parse_price_to_cents(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .strip()
    )
    if not cleaned:
        return None
    try:
        cents = int(Decimal(cleaned) * 100)
        return cents if cents >= 0 else None
    except Exception:
        return None


def _normalize_row(row: Dict[str, str]) -> Optional[Dict]:
    normalized = { (key or "").strip().lower(): value for key, value in row.items() }
    sku = (normalized.get("sku") or "").strip()
    if not sku:
        return None
    active_value = (normalized.get("active") or "").strip().lower()
    active = True
    if active_value in {"false", "0", "no", "inactive"}:
        active = False
    price_cents = (
        _parse_price_to_cents(normalized.get("price_cents"))
        or _parse_price_to_cents(normalized.get("price"))
    )
    return {
        "sku": sku,
        "name": (normalized.get("name") or "").strip() or None,
        "description": (normalized.get("description") or "").strip() or None,
        "price_cents": price_cents,
        "active": active,
    }


def _dedupe_batch(rows: List[Dict]) -> List[Dict]:
    deduped = {}
    for item in rows:
        deduped[item["sku"].lower()] = item
    return list(deduped.values())


@celery.task(bind=True, name="app.tasks.import_products_task")
def import_products_task(self, file_path):
    task_id = self.request.id
    _set_task_state(task_id, status="initializing", progress=0, total=0, invalid=0)

    batch = []
    batch_size = int(os.getenv("IMPORT_BATCH_SIZE", "5000"))
    processed = 0
    invalid_rows = 0

    try:
        total_rows = _count_rows(file_path)
        _set_task_state(task_id, status="parsing", total=total_rows)

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
            if not headers or "sku" not in headers:
                raise ValueError("CSV must include an 'sku' column")

            for row in reader:
                product = _normalize_row(row)
                if not product:
                    invalid_rows += 1
                    continue

                batch.append(product)
                if len(batch) >= batch_size:
                    processed += upsert_products_bulk(_dedupe_batch(batch))
                    batch = []
                    _set_task_state(
                        task_id,
                        status=f"importing ({processed}/{total_rows})",
                        progress=processed,
                        invalid=invalid_rows,
                    )

            if batch:
                processed += upsert_products_bulk(_dedupe_batch(batch))

        _set_task_state(
            task_id,
            status="complete",
            progress=processed,
            total=total_rows,
            invalid=invalid_rows,
        )
    except Exception as exc:
        _set_task_state(task_id, status=f"error: {exc}", error=str(exc))
        raise
    finally:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass

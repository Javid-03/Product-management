from typing import Iterable, List, Dict
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from .models import Product
from .database import engine


def upsert_products_bulk(rows: Iterable[Dict], chunk_size: int = 5000) -> int:
    """
    Insert or update products in bulk, de-duplicating by the case-insensitive SKU constraint.
    Returns the number of rows processed (created or updated).
    """
    rows_list: List[Dict] = rows if isinstance(rows, list) else list(rows)
    if not rows_list:
        return 0

    processed = 0
    with engine.begin() as conn:
        for i in range(0, len(rows_list), chunk_size):
            chunk = rows_list[i : i + chunk_size]
            stmt = insert(Product).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[func.lower(Product.sku)],
                set_={
                    "name": stmt.excluded.name,
                    "description": stmt.excluded.description,
                    "price_cents": stmt.excluded.price_cents,
                    "active": stmt.excluded.active,
                },
            )
            result = conn.execute(stmt)
            processed += result.rowcount or len(chunk)
    return processed

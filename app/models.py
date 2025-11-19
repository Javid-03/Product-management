from sqlalchemy import Column, Integer, String, Boolean, Index, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from .database import Base
from datetime import datetime

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(300), nullable=True)
    description = Column(String(2000), nullable=True)
    price_cents = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # create case-insensitive unique constraint on lower(sku)
        Index("ix_products_lower_sku_unique", func.lower(sku), unique=True),
    )

class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(Integer, primary_key=True)
    url = Column(String(1000), nullable=False)
    event = Column(String(100), nullable=False)  # e.g., product.imported
    enabled = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

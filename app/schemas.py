from pydantic import BaseModel, HttpUrl
from typing import Optional

class ProductCreate(BaseModel):
    sku: str
    name: Optional[str]
    description: Optional[str]
    price_cents: Optional[int]
    active: Optional[bool] = True

class ProductOut(ProductCreate):
    id: int

    class Config:
        orm_mode = True

class WebhookCreate(BaseModel):
    url: HttpUrl
    event: str
    enabled: Optional[bool] = True

class WebhookOut(WebhookCreate):
    id: int
    class Config:
        orm_mode = True

from datetime import datetime

from pydantic import BaseModel


class OrderPartColourBase(BaseModel):
    library_file_id: int | None = None
    filament_index: int
    colour_hex: str
    colour_name: str | None = None
    material: str = "PLA"


class OrderItemBase(BaseModel):
    product_id: int | None = None
    quantity: int = 1


class OrderItemCreate(OrderItemBase):
    part_colours: list[OrderPartColourBase] = []


class OrderItemResponse(OrderItemBase):
    id: int
    order_id: int
    status: str
    part_colours: list[OrderPartColourBase] = []

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    marketplace: str
    order_ref: str
    buyer: str | None = None
    notes: str | None = None
    items: list[OrderItemCreate] = []


class OrderUpdate(BaseModel):
    buyer: str | None = None
    status: str | None = None
    notes: str | None = None
    fulfilled_at: datetime | None = None


class OrderResponse(BaseModel):
    id: int
    marketplace: str
    order_ref: str
    buyer: str | None
    status: str
    notes: str | None
    received_at: datetime
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = []

    model_config = {"from_attributes": True}


class OrderListItem(BaseModel):
    id: int
    marketplace: str
    order_ref: str
    buyer: str | None
    status: str
    received_at: datetime
    item_count: int

    model_config = {"from_attributes": True}


class ProductPartResponse(BaseModel):
    id: int
    library_file_id: int | None
    quantity: int

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    sku: str | None = None
    marketplace: str | None = None
    listing_id: str | None = None
    title: str
    notes: str | None = None


class ProductResponse(BaseModel):
    id: int
    sku: str | None
    marketplace: str | None
    listing_id: str | None
    title: str
    notes: str | None
    parts: list[ProductPartResponse] = []

    model_config = {"from_attributes": True}

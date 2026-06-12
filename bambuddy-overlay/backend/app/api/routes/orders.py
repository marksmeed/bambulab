"""Smokeforge fulfilment — orders, products, and job tracking."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.models.fulfilment_job import FulfilmentJob
from backend.app.models.order import Order, OrderItem, OrderPartColour
from backend.app.models.product import Product, ProductPart
from backend.app.schemas.order import (
    OrderCreate,
    OrderListItem,
    OrderResponse,
    OrderUpdate,
    ProductCreate,
    ProductResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])

VALID_ORDER_STATUSES = {"new", "allocated", "printing", "printed", "shipped", "cancelled"}
VALID_ITEM_STATUSES = {"pending", "allocated", "printing", "done", "failed"}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.get("", response_model=list[OrderListItem])
async def list_orders(
    status: str | None = None,
    marketplace: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:read")),
):
    stmt = select(
        Order.id,
        Order.marketplace,
        Order.order_ref,
        Order.buyer,
        Order.status,
        Order.received_at,
        func.count(OrderItem.id).label("item_count"),
    ).outerjoin(OrderItem, OrderItem.order_id == Order.id).group_by(Order.id)

    if status:
        stmt = stmt.where(Order.status == status)
    if marketplace:
        stmt = stmt.where(Order.marketplace == marketplace)

    stmt = stmt.order_by(Order.received_at.desc())
    rows = (await db.execute(stmt)).all()

    return [
        OrderListItem(
            id=r.id,
            marketplace=r.marketplace,
            order_ref=r.order_ref,
            buyer=r.buyer,
            status=r.status,
            received_at=r.received_at,
            item_count=r.item_count,
        )
        for r in rows
    ]


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:create")),
):
    existing = await db.execute(
        select(Order).where(Order.marketplace == payload.marketplace, Order.order_ref == payload.order_ref)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Order reference already exists for this marketplace")

    order = Order(
        marketplace=payload.marketplace,
        order_ref=payload.order_ref,
        buyer=payload.buyer,
        notes=payload.notes,
    )
    db.add(order)
    await db.flush()

    for item_data in payload.items:
        item = OrderItem(order_id=order.id, product_id=item_data.product_id, quantity=item_data.quantity)
        db.add(item)
        await db.flush()
        for colour in item_data.part_colours:
            db.add(OrderPartColour(
                order_item_id=item.id,
                library_file_id=colour.library_file_id,
                filament_index=colour.filament_index,
                colour_hex=colour.colour_hex,
                colour_name=colour.colour_name,
                material=colour.material,
            ))

    await db.flush()
    return await _load_order(order.id, db)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:read")),
):
    order = await _load_order(order_id, db)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:update")),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if payload.status and payload.status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {VALID_ORDER_STATUSES}")
    if payload.buyer is not None:
        order.buyer = payload.buyer
    if payload.status is not None:
        order.status = payload.status
        if payload.status == "shipped" and not order.fulfilled_at:
            order.fulfilled_at = datetime.now(timezone.utc)
    if payload.notes is not None:
        order.notes = payload.notes
    if payload.fulfilled_at is not None:
        order.fulfilled_at = payload.fulfilled_at
    return await _load_order(order_id, db)


@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:delete")),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.delete(order)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@router.get("/products/", response_model=list[ProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:read")),
):
    stmt = select(Product).options(selectinload(Product.parts)).order_by(Product.title)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/products/", response_model=ProductResponse, status_code=201)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RequirePermissionIfAuthEnabled("orders:create")),
):
    product = Product(
        sku=payload.sku,
        marketplace=payload.marketplace,
        listing_id=payload.listing_id,
        title=payload.title,
        notes=payload.notes,
    )
    db.add(product)
    await db.flush()
    stmt = select(Product).options(selectinload(Product.parts)).where(Product.id == product.id)
    return (await db.execute(stmt)).scalar_one()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_order(order_id: int, db: AsyncSession) -> OrderResponse | None:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.part_colours),
        )
        .where(Order.id == order_id)
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        return None
    return OrderResponse.model_validate(order)

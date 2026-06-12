from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class Order(Base):
    __tablename__ = "sf_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(20))   # etsy / ebay / amazon / manual
    order_ref: Mapped[str] = mapped_column(String(100))
    buyer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    # new / allocated / printing / printed / shipped / cancelled
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "sf_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sf_orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("sf_products.id", ondelete="SET NULL"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending / allocated / printing / done / failed

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="order_items")
    part_colours: Mapped[list["OrderPartColour"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")
    fulfilment_jobs: Mapped[list["FulfilmentJob"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")


class OrderPartColour(Base):
    """Buyer's colour choice per 3MF file per filament slot in an order item."""

    __tablename__ = "sf_order_part_colours"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("sf_order_items.id", ondelete="CASCADE"))
    library_file_id: Mapped[int | None] = mapped_column(ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True)
    filament_index: Mapped[int] = mapped_column(Integer)
    colour_hex: Mapped[str] = mapped_column(String(9))
    colour_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    material: Mapped[str] = mapped_column(String(20), default="PLA")

    order_item: Mapped["OrderItem"] = relationship(back_populates="part_colours")


from backend.app.models.fulfilment_job import FulfilmentJob  # noqa: E402
from backend.app.models.product import Product  # noqa: E402

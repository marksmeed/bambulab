from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class Product(Base):
    """A marketplace listing — maps to one or more 3MF files (parts)."""

    __tablename__ = "sf_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(20), nullable=True)  # etsy / ebay / amazon
    listing_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("marketplace", "listing_id", name="uq_sf_product_listing"),)

    parts: Mapped[list["ProductPart"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")


class ProductPart(Base):
    """One 3MF file required to fulfil a product (printed separately)."""

    __tablename__ = "sf_product_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("sf_products.id", ondelete="CASCADE"))
    library_file_id: Mapped[int | None] = mapped_column(ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    product: Mapped["Product"] = relationship(back_populates="parts")


from backend.app.models.order import OrderItem  # noqa: E402

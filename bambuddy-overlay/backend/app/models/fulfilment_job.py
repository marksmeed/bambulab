from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class FulfilmentJob(Base):
    """One print job for one 3MF on one printer, linked to an order item."""

    __tablename__ = "sf_fulfilment_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("sf_order_items.id", ondelete="SET NULL"), nullable=True)
    library_file_id: Mapped[int | None] = mapped_column(ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True)
    printer_id: Mapped[int | None] = mapped_column(ForeignKey("printers.id", ondelete="SET NULL"), nullable=True)
    # Link to Bambuddy's own queue/archive once dispatched
    bambu_queue_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    # queued / printing / finished / failed / cancelled
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    order_item: Mapped["OrderItem | None"] = relationship(back_populates="fulfilment_jobs")
    filaments: Mapped[list["FulfilmentJobFilament"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class FulfilmentJobFilament(Base):
    """Resolved colour→slot mapping for one filament position in a fulfilment job."""

    __tablename__ = "sf_fulfilment_job_filaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("sf_fulfilment_jobs.id", ondelete="CASCADE"))
    filament_index: Mapped[int] = mapped_column(Integer)
    requested_colour_hex: Mapped[str | None] = mapped_column(String(9), nullable=True)
    assigned_ams_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_slot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped["FulfilmentJob"] = relationship(back_populates="filaments")


from backend.app.models.order import OrderItem  # noqa: E402

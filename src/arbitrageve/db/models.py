from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from arbitrageve.db.database import Base


class Item(Base):
    __tablename__ = "items"

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    volume: Mapped[float] = mapped_column(Float, default=0)


class MarketOrder(Base):
    __tablename__ = "market_orders"

    order_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(Integer, index=True)
    system_id: Mapped[int] = mapped_column(Integer, index=True)
    location_id: Mapped[int] = mapped_column(Integer, index=True)
    type_id: Mapped[int] = mapped_column(Integer, index=True)
    price: Mapped[float] = mapped_column(Float)
    volume_remain: Mapped[int] = mapped_column(Integer)
    volume_total: Mapped[int] = mapped_column(Integer)
    is_buy_order: Mapped[bool] = mapped_column(Boolean, index=True)
    issued: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    __table_args__ = (
        Index("ix_market_orders_region_type_side", "region_id", "type_id", "is_buy_order"),
        Index("ix_market_orders_type_price", "type_id", "price"),
    )

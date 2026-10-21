"""Customer master data and versioned sales orders; no stock effects in this slice."""

from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Row


class Customer(Row, Base):
    __tablename__ = "customer"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    contact: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(60))
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesOrder(Row, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        CheckConstraint("total >= 0"),
        CheckConstraint("status IN ('draft','submitted','approved','cancelled')"),
        CheckConstraint(
            "(status <> 'approved' OR approved_by IS NOT NULL) AND (status NOT IN ('draft','submitted') OR approved_by IS NULL)"
        ),
    )
    number: Mapped[str] = mapped_column(String(50), unique=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)


class SalesLine(Row, Base):
    __tablename__ = "sales_line"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number"),
        CheckConstraint("line_number > 0 AND quantity > 0"),
        CheckConstraint("unit_price >= 0 AND amount >= 0"),
    )
    order_id: Mapped[str] = mapped_column(ForeignKey("sales_order.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

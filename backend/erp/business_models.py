from decimal import Decimal

from sqlalchemy import (
    JSON,
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


class Category(Row, Base):
    __tablename__ = "category"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("category.id"), index=True)


class Supplier(Row, Base):
    __tablename__ = "supplier"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    contact: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(60))
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(Row, Base):
    __tablename__ = "warehouse"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PurchaseOrder(Row, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        CheckConstraint("total >= 0"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','partially_received','received','cancelled')"
        ),
    )
    number: Mapped[str] = mapped_column(String(50), unique=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("supplier.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("erp_user.id"), index=True)


class PurchaseLine(Row, Base):
    __tablename__ = "purchase_line"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number"),
        CheckConstraint(
            "quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity"
        ),
        CheckConstraint("unit_price >= 0 AND amount >= 0"),
    )
    order_id: Mapped[str] = mapped_column(ForeignKey("purchase_order.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))


class PurchaseReceipt(Row, Base):
    __tablename__ = "purchase_receipt"
    number: Mapped[str] = mapped_column(String(50), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("purchase_order.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouse.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)


class ReceiptLine(Row, Base):
    __tablename__ = "receipt_line"
    __table_args__ = (
        UniqueConstraint("receipt_id", "purchase_line_id"),
        CheckConstraint("quantity > 0"),
    )
    receipt_id: Mapped[str] = mapped_column(ForeignKey("purchase_receipt.id"), index=True)
    purchase_line_id: Mapped[str] = mapped_column(ForeignKey("purchase_line.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class InventoryBalance(Row, Base):
    __tablename__ = "inventory_balance"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id"),
        CheckConstraint("quantity >= 0"),
    )
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouse.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))


class StockMovement(Row, Base):
    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint("quantity > 0"),
        CheckConstraint(
            "(kind = 'purchase_receipt' AND receipt_line_id IS NOT NULL AND shipment_line_id IS NULL) OR (kind = 'sales_shipment' AND receipt_line_id IS NULL AND shipment_line_id IS NOT NULL)",
            name="ck_stock_movement_source",
        ),
        UniqueConstraint("shipment_line_id", name="uq_stock_movement_shipment_line"),
    )
    shipment_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("shipment_line.id", name="fk_stock_movement_shipment_line")
    )
    receipt_line_id: Mapped[str | None] = mapped_column(ForeignKey("receipt_line.id"), unique=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouse.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    kind: Mapped[str] = mapped_column(String(30), default="purchase_receipt")


class CommandExecution(Row, Base):
    __tablename__ = "command_execution"
    __table_args__ = (UniqueConstraint("subject_id", "key"),)
    subject_id: Mapped[str] = mapped_column(ForeignKey("erp_user.id"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    payload_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[str] = mapped_column(ForeignKey("purchase_receipt.id"), index=True)


class SystemConfiguration(Base):
    __tablename__ = "system_configuration"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    values: Mapped[dict] = mapped_column(JSON)


class Outbox(Row, Base):
    __tablename__ = "outbox"
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    dispatched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

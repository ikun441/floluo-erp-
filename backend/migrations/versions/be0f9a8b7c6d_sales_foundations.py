"""Add customer master data and sales draft/approval records; preserve published schemas."""

import sqlalchemy as sa
from alembic import op

revision = "be0f9a8b7c6d"
down_revision = "ad9e8f7a6b5c"
branch_labels = None
depends_on = None


def row_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def owned_columns():
    return [
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("department.id")),
    ]


def upgrade():
    op.create_table(
        "customer",
        *row_columns(),
        sa.Column("code", sa.String(80), unique=True, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("contact", sa.String(120)),
        sa.Column("phone", sa.String(60)),
        *owned_columns(),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "sales_order",
        *row_columns(),
        sa.Column("number", sa.String(50), unique=True, nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customer.id"), nullable=False),
        *owned_columns(),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("erp_user.id")),
        sa.CheckConstraint("total >= 0"),
        sa.CheckConstraint("status IN ('draft','submitted','approved','cancelled')"),
        sa.CheckConstraint(
            "(status <> 'approved' OR approved_by IS NOT NULL) AND (status NOT IN ('draft','submitted') OR approved_by IS NULL)"
        ),
    )
    op.create_table(
        "sales_line",
        *row_columns(),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("order_id", "line_number"),
        sa.CheckConstraint("line_number > 0 AND quantity > 0"),
        sa.CheckConstraint("unit_price >= 0 AND amount >= 0"),
    )
    for table, fields in {
        "customer": ("owner_id", "department_id"),
        "sales_order": ("customer_id", "owner_id", "department_id", "status", "approved_by"),
        "sales_line": ("order_id", "product_id"),
    }.items():
        for field in fields:
            op.create_index("ix_" + table + "_" + field, table, [field])


def downgrade():
    db = op.get_bind()
    if any(
        db.scalar(sa.text("SELECT COUNT(*) FROM " + table))
        for table in ("sales_line", "sales_order", "customer")
    ):
        raise RuntimeError("sales/customer data exists; downgrade would destroy business history")
    for table in ("sales_line", "sales_order", "customer"):
        op.drop_table(table)

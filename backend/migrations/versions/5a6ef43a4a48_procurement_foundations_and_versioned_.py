"""procurement foundations and versioned audit summaries"""

import sqlalchemy as sa
from alembic import op

revision = "5a6ef43a4a48"
down_revision = "724dfa42fcdd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "category",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["category.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_category_parent_id"), "category", ["parent_id"], unique=False)
    op.create_table(
        "outbox",
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dispatched", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_aggregate_id"), "outbox", ["aggregate_id"], unique=False)
    op.create_index(op.f("ix_outbox_dispatched"), "outbox", ["dispatched"], unique=False)
    op.create_index(op.f("ix_outbox_event_type"), "outbox", ["event_type"], unique=False)
    op.create_table(
        "system_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "supplier",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=60), nullable=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_supplier_department_id"), "supplier", ["department_id"], unique=False)
    op.create_index(op.f("ix_supplier_owner_id"), "supplier", ["owner_id"], unique=False)
    op.create_table(
        "warehouse",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        op.f("ix_warehouse_department_id"), "warehouse", ["department_id"], unique=False
    )
    op.create_index(op.f("ix_warehouse_owner_id"), "warehouse", ["owner_id"], unique=False)
    op.create_table(
        "inventory_balance",
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity >= 0"),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouse.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "product_id"),
    )
    op.create_index(
        op.f("ix_inventory_balance_department_id"),
        "inventory_balance",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_balance_owner_id"), "inventory_balance", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_balance_product_id"), "inventory_balance", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_balance_warehouse_id"),
        "inventory_balance",
        ["warehouse_id"],
        unique=False,
    )
    op.create_table(
        "purchase_order",
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','partially_received','received','cancelled')"
        ),
        sa.CheckConstraint("total >= 0"),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["erp_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["supplier.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index(
        op.f("ix_purchase_order_approved_by"), "purchase_order", ["approved_by"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_order_department_id"), "purchase_order", ["department_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_order_owner_id"), "purchase_order", ["owner_id"], unique=False
    )
    op.create_index(op.f("ix_purchase_order_status"), "purchase_order", ["status"], unique=False)
    op.create_index(
        op.f("ix_purchase_order_supplier_id"), "purchase_order", ["supplier_id"], unique=False
    )
    op.create_table(
        "purchase_line",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("received_quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity"
        ),
        sa.CheckConstraint("unit_price >= 0 AND amount >= 0"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["purchase_order.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "line_number"),
    )
    op.create_index(op.f("ix_purchase_line_order_id"), "purchase_line", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_purchase_line_product_id"), "purchase_line", ["product_id"], unique=False
    )
    op.create_table(
        "purchase_receipt",
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["purchase_order.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouse.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index(
        op.f("ix_purchase_receipt_department_id"),
        "purchase_receipt",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_receipt_order_id"), "purchase_receipt", ["order_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_receipt_owner_id"), "purchase_receipt", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_receipt_warehouse_id"), "purchase_receipt", ["warehouse_id"], unique=False
    )
    op.create_table(
        "command_execution",
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["purchase_receipt.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["erp_user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "key"),
    )
    op.create_index(
        op.f("ix_command_execution_receipt_id"), "command_execution", ["receipt_id"], unique=False
    )
    op.create_index(
        op.f("ix_command_execution_subject_id"), "command_execution", ["subject_id"], unique=False
    )
    op.create_table(
        "receipt_line",
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("purchase_line_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
        ),
        sa.ForeignKeyConstraint(
            ["purchase_line_id"],
            ["purchase_line.id"],
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["purchase_receipt.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "purchase_line_id"),
    )
    op.create_index(
        op.f("ix_receipt_line_product_id"), "receipt_line", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_receipt_line_purchase_line_id"), "receipt_line", ["purchase_line_id"], unique=False
    )
    op.create_index(
        op.f("ix_receipt_line_receipt_id"), "receipt_line", ["receipt_id"], unique=False
    )
    op.create_table(
        "stock_movement",
        sa.Column("receipt_line_id", sa.String(length=36), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0"),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["department.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["erp_user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
        ),
        sa.ForeignKeyConstraint(
            ["receipt_line_id"],
            ["receipt_line.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouse.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_line_id"),
    )
    op.create_index(
        op.f("ix_stock_movement_department_id"), "stock_movement", ["department_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movement_owner_id"), "stock_movement", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movement_product_id"), "stock_movement", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movement_warehouse_id"), "stock_movement", ["warehouse_id"], unique=False
    )
    op.add_column(
        "audit_event", sa.Column("format_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("audit_event", sa.Column("details", sa.JSON(), nullable=True))
    with op.batch_alter_table("product") as batch:
        batch.add_column(sa.Column("category_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_product_category_id", ["category_id"], unique=False)
        batch.create_foreign_key(
            "fk_product_category_id_category", "category", ["category_id"], ["id"]
        )
    op.bulk_insert(
        sa.table(
            "system_configuration",
            sa.column("id", sa.Integer()),
            sa.column("version", sa.Integer()),
            sa.column("values", sa.JSON()),
        ),
        [
            {
                "id": 1,
                "version": 1,
                "values": {
                    "supported_currencies": [],
                    "tax_mode": "unconfigured",
                    "require_separate_approver": True,
                },
            }
        ],
    )
    for table in ("purchase_receipt", "receipt_line", "stock_movement", "command_execution"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION erp_reject_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION erp_reject_mutation()"
            )
        elif op.get_bind().dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
                )


def downgrade():
    # Never silently discard business records or make audit v2 unverifiable.
    for table in (
        "category",
        "supplier",
        "warehouse",
        "purchase_order",
        "purchase_receipt",
        "inventory_balance",
        "stock_movement",
        "outbox",
        "command_execution",
    ):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError(
                "Nonempty business schema: restore a verified backup instead of destructive downgrade"
            )
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM audit_event WHERE format_version <> 1")):
        raise RuntimeError("Audit v2 records exist: keep this schema to preserve verifiability")
    with op.batch_alter_table("product") as batch:
        batch.drop_constraint("fk_product_category_id_category", type_="foreignkey")
        batch.drop_index("ix_product_category_id")
        batch.drop_column("category_id")
    op.drop_column("audit_event", "details")
    op.drop_column("audit_event", "format_version")
    op.drop_index(op.f("ix_stock_movement_warehouse_id"), table_name="stock_movement")
    op.drop_index(op.f("ix_stock_movement_product_id"), table_name="stock_movement")
    op.drop_index(op.f("ix_stock_movement_owner_id"), table_name="stock_movement")
    op.drop_index(op.f("ix_stock_movement_department_id"), table_name="stock_movement")
    op.drop_table("stock_movement")
    op.drop_index(op.f("ix_receipt_line_receipt_id"), table_name="receipt_line")
    op.drop_index(op.f("ix_receipt_line_purchase_line_id"), table_name="receipt_line")
    op.drop_index(op.f("ix_receipt_line_product_id"), table_name="receipt_line")
    op.drop_table("receipt_line")
    op.drop_index(op.f("ix_command_execution_subject_id"), table_name="command_execution")
    op.drop_index(op.f("ix_command_execution_receipt_id"), table_name="command_execution")
    op.drop_table("command_execution")
    op.drop_index(op.f("ix_purchase_receipt_warehouse_id"), table_name="purchase_receipt")
    op.drop_index(op.f("ix_purchase_receipt_owner_id"), table_name="purchase_receipt")
    op.drop_index(op.f("ix_purchase_receipt_order_id"), table_name="purchase_receipt")
    op.drop_index(op.f("ix_purchase_receipt_department_id"), table_name="purchase_receipt")
    op.drop_table("purchase_receipt")
    op.drop_index(op.f("ix_purchase_line_product_id"), table_name="purchase_line")
    op.drop_index(op.f("ix_purchase_line_order_id"), table_name="purchase_line")
    op.drop_table("purchase_line")
    op.drop_index(op.f("ix_purchase_order_supplier_id"), table_name="purchase_order")
    op.drop_index(op.f("ix_purchase_order_status"), table_name="purchase_order")
    op.drop_index(op.f("ix_purchase_order_owner_id"), table_name="purchase_order")
    op.drop_index(op.f("ix_purchase_order_department_id"), table_name="purchase_order")
    op.drop_index(op.f("ix_purchase_order_approved_by"), table_name="purchase_order")
    op.drop_table("purchase_order")
    op.drop_index(op.f("ix_inventory_balance_warehouse_id"), table_name="inventory_balance")
    op.drop_index(op.f("ix_inventory_balance_product_id"), table_name="inventory_balance")
    op.drop_index(op.f("ix_inventory_balance_owner_id"), table_name="inventory_balance")
    op.drop_index(op.f("ix_inventory_balance_department_id"), table_name="inventory_balance")
    op.drop_table("inventory_balance")
    op.drop_index(op.f("ix_warehouse_owner_id"), table_name="warehouse")
    op.drop_index(op.f("ix_warehouse_department_id"), table_name="warehouse")
    op.drop_table("warehouse")
    op.drop_index(op.f("ix_supplier_owner_id"), table_name="supplier")
    op.drop_index(op.f("ix_supplier_department_id"), table_name="supplier")
    op.drop_table("supplier")
    op.drop_table("system_configuration")
    op.drop_index(op.f("ix_outbox_event_type"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_dispatched"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_aggregate_id"), table_name="outbox")
    op.drop_table("outbox")
    op.drop_index(op.f("ix_category_parent_id"), table_name="category")
    op.drop_table("category")

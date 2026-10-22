"""Sales shipments and append-only directional stock ledger; retain all old rows."""

import sqlalchemy as sa
from alembic import op

revision = "ce1a0b9c8d7e"
down_revision = "be0f9a8b7c6d"
branch_labels = None
depends_on = None

SOURCE = "(kind = 'purchase_receipt' AND receipt_line_id IS NOT NULL AND shipment_line_id IS NULL) OR (kind = 'sales_shipment' AND receipt_line_id IS NULL AND shipment_line_id IS NOT NULL)"


def sqlite_transaction():
    db = op.get_bind()
    if db.dialect.name == "sqlite":
        if db.scalar(sa.text("PRAGMA foreign_keys")):
            raise RuntimeError(
                "Run this offline Alembic migration with its dedicated SQLite connection; table rebuild requires foreign_keys=OFF"
            )
        if not db.connection.driver_connection.in_transaction:
            op.execute("BEGIN")
        if db.execute(sa.text("PRAGMA foreign_key_check")).first():
            raise RuntimeError("Existing SQLite foreign key violations; repair before migration")


def immutable(table, create=True):
    if op.get_bind().dialect.name == "postgresql":
        if create:
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION erp_reject_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION erp_reject_mutation()"
            )
        else:
            op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
            op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
    else:
        for action in ("UPDATE", "DELETE"):
            if create:
                op.execute(
                    f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
                )
            else:
                op.execute(f"DROP TRIGGER {table}_{action.lower()}_guard")


def row_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def order_states(up):
    # Reflection discovers PostgreSQL's generated names; explicitly name SQLite's old checks.
    table = sa.Table("sales_order", sa.MetaData(), autoload_with=op.get_bind())
    checks = [
        c
        for c in table.constraints
        if isinstance(c, sa.CheckConstraint) and "status" in str(c.sqltext)
    ]
    for index, constraint in enumerate(checks):
        if constraint.name is None:
            constraint.name = "ck_sales_order_legacy_" + str(index)
    states = (
        "'draft','submitted','approved','partially_shipped','shipped','cancelled'"
        if up
        else "'draft','submitted','approved','cancelled'"
    )
    approved = "'approved','partially_shipped','shipped'" if up else "'approved'"
    with op.batch_alter_table("sales_order", copy_from=table) as batch:
        for constraint in checks:
            batch.drop_constraint(constraint.name, type_="check")
        batch.create_check_constraint("ck_sales_order_status", f"status IN ({states})")
        batch.create_check_constraint(
            "ck_sales_order_approval",
            f"(status NOT IN ({approved}) OR approved_by IS NOT NULL) AND (status NOT IN ('draft','submitted') OR approved_by IS NULL)",
        )


def upgrade():
    sqlite_transaction()
    order_states(True)
    with op.batch_alter_table(
        "sales_line", copy_from=sa.Table("sales_line", sa.MetaData(), autoload_with=op.get_bind())
    ) as batch:
        batch.add_column(
            sa.Column("shipped_quantity", sa.Numeric(18, 4), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            "ck_sales_line_shipped_quantity",
            "shipped_quantity >= 0 AND shipped_quantity <= quantity",
        )
    op.create_table(
        "sales_shipment",
        *row_columns(),
        sa.Column("number", sa.String(50), unique=True, nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("warehouse_id", sa.String(36), sa.ForeignKey("warehouse.id"), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("department.id")),
    )
    op.create_table(
        "shipment_line",
        *row_columns(),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("sales_shipment.id"), nullable=False),
        sa.Column("sales_line_id", sa.String(36), sa.ForeignKey("sales_line.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("shipment_id", "sales_line_id"),
        sa.CheckConstraint("quantity > 0"),
    )
    op.create_table(
        "shipment_execution",
        *row_columns(),
        sa.Column("subject_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("sales_shipment.id"), nullable=False),
        sa.UniqueConstraint("subject_id", "key"),
        sa.UniqueConstraint("shipment_id"),
    )
    for table, fields in {
        "sales_shipment": ("order_id", "warehouse_id", "owner_id", "department_id"),
        "shipment_line": ("shipment_id", "sales_line_id", "product_id"),
        "shipment_execution": ("subject_id", "shipment_id"),
    }.items():
        for field in fields:
            op.create_index("ix_" + table + "_" + field, table, [field])
    immutable("stock_movement", False)
    with op.batch_alter_table(
        "stock_movement",
        copy_from=sa.Table("stock_movement", sa.MetaData(), autoload_with=op.get_bind()),
    ) as batch:
        batch.alter_column("receipt_line_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("shipment_line_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_stock_movement_shipment_line", "shipment_line", ["shipment_line_id"], ["id"]
        )
        batch.create_unique_constraint("uq_stock_movement_shipment_line", ["shipment_line_id"])
        batch.create_check_constraint("ck_stock_movement_source", SOURCE)
    for table in ("stock_movement", "sales_shipment", "shipment_line", "shipment_execution"):
        immutable(table)
    if (
        op.get_bind().dialect.name == "sqlite"
        and op.get_bind().execute(sa.text("PRAGMA foreign_key_check")).first()
    ):
        raise RuntimeError("Foreign key check failed after shipment migration")


def downgrade():
    sqlite_transaction()
    db = op.get_bind()
    if (
        any(
            db.scalar(sa.text("SELECT COUNT(*) FROM " + table))
            for table in ("sales_shipment", "shipment_line", "shipment_execution")
        )
        or db.scalar(sa.text("SELECT COUNT(*) FROM sales_line WHERE shipped_quantity <> 0"))
        or db.scalar(
            sa.text(
                "SELECT COUNT(*) FROM sales_order WHERE status IN ('partially_shipped','shipped')"
            )
        )
        or db.scalar(
            sa.text("SELECT COUNT(*) FROM stock_movement WHERE shipment_line_id IS NOT NULL")
        )
    ):
        raise RuntimeError("shipment history exists; downgrade would destroy fulfillment data")
    immutable("stock_movement", False)
    with op.batch_alter_table(
        "stock_movement",
        copy_from=sa.Table("stock_movement", sa.MetaData(), autoload_with=op.get_bind()),
    ) as batch:
        batch.drop_constraint("ck_stock_movement_source", type_="check")
        batch.drop_constraint("uq_stock_movement_shipment_line", type_="unique")
        batch.drop_constraint("fk_stock_movement_shipment_line", type_="foreignkey")
        batch.drop_column("shipment_line_id")
        batch.alter_column("receipt_line_id", existing_type=sa.String(36), nullable=False)
    immutable("stock_movement")
    for table in ("shipment_execution", "shipment_line", "sales_shipment"):
        op.drop_table(table)
    with op.batch_alter_table(
        "sales_line", copy_from=sa.Table("sales_line", sa.MetaData(), autoload_with=op.get_bind())
    ) as batch:
        batch.drop_constraint("ck_sales_line_shipped_quantity", type_="check")
        batch.drop_column("shipped_quantity")
    order_states(False)
    if db.dialect.name == "sqlite" and db.execute(sa.text("PRAGMA foreign_key_check")).first():
        raise RuntimeError("Foreign key check failed after shipment downgrade")

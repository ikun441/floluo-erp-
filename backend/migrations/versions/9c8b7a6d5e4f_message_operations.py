"""Persistent operation previews and password-confirmed purchase drafts."""

import sqlalchemy as sa
from alembic import op

revision = "9c8b7a6d5e4f"
down_revision = "8b7a6c5d4e3f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_operation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("binding_id", sa.String(36), sa.ForeignKey("message_binding.id")),
        sa.Column("binding_version", sa.Integer()),
        sa.Column("resource", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("target_order_id", sa.String(36), nullable=False, unique=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preview_digest", sa.String(64)),
        sa.Column("result_id", sa.String(36), sa.ForeignKey("purchase_order.id"), unique=True),
        sa.Column("confirmed_version", sa.Integer()),
        sa.CheckConstraint(
            "state IN ('collecting_missing','awaiting_confirmation','completed','cancelled','expired')"
        ),
        sa.CheckConstraint("resource = 'purchase_orders'"),
        sa.CheckConstraint(
            "(binding_id IS NULL AND binding_version IS NULL) OR (binding_id IS NOT NULL AND binding_version IS NOT NULL AND binding_version >= 1)"
        ),
        sa.CheckConstraint(
            "(state = 'completed' AND result_id IS NOT NULL AND confirmed_version IS NOT NULL) OR (state <> 'completed' AND result_id IS NULL AND confirmed_version IS NULL)"
        ),
        sa.CheckConstraint(
            "state NOT IN ('awaiting_confirmation','completed') OR preview_digest IS NOT NULL"
        ),
        sa.CheckConstraint("result_id IS NULL OR result_id = target_order_id"),
    )
    for field in ("owner_id", "binding_id", "state", "expires_at"):
        op.create_index("ix_message_operation_" + field, "message_operation", [field])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM message_operation")):
        raise RuntimeError("message operations exist; downgrade would destroy confirmation history")
    op.drop_table("message_operation")

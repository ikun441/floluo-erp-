"""Durable reply recipes and fenced reverse WebSocket connection leases."""

import sqlalchemy as sa
from alembic import op

revision = "ad9e8f7a6b5c"
down_revision = "9c8b7a6d5e4f"
branch_labels = None
depends_on = None


def row_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "onebot_connection",
        *row_columns(),
        sa.Column(
            "instance_id",
            sa.String(36),
            sa.ForeignKey("onebot_instance.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("connection_id", sa.String(36), unique=True, nullable=False),
        sa.Column("instance_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("disconnect_reason", sa.String(32)),
        sa.CheckConstraint("state IN ('connected','disconnected')"),
        sa.CheckConstraint("instance_version >= 1"),
    )
    op.create_table(
        "message_delivery",
        *row_columns(),
        sa.Column(
            "event_key",
            sa.String(64),
            sa.ForeignKey("message_inbox.event_key"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "instance_id", sa.String(36), sa.ForeignKey("onebot_instance.id"), nullable=False
        ),
        sa.Column("recipient_id", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id")),
        sa.Column("binding_id", sa.String(36), sa.ForeignKey("message_binding.id")),
        sa.Column("binding_version", sa.Integer()),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_token", sa.String(36)),
        sa.Column("attempt_connection_id", sa.String(36)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(32)),
        sa.CheckConstraint(
            "state IN ('pending','awaiting_ack','delivered','failed','suppressed','expired')"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3"),
        sa.CheckConstraint(
            "(binding_id IS NULL AND binding_version IS NULL) OR (binding_id IS NOT NULL AND binding_version IS NOT NULL AND binding_version >= 1)"
        ),
        sa.CheckConstraint(
            "state <> 'awaiting_ack' OR (attempt_token IS NOT NULL AND attempt_connection_id IS NOT NULL AND attempts >= 1)"
        ),
        sa.CheckConstraint(
            "(state = 'delivered' AND delivered_at IS NOT NULL) OR (state <> 'delivered' AND delivered_at IS NULL)"
        ),
    )
    for field in ("instance_id", "owner_id", "binding_id", "expires_at"):
        op.create_index("ix_message_delivery_" + field, "message_delivery", [field])
    op.create_index(
        "ix_message_delivery_due", "message_delivery", ["instance_id", "state", "next_attempt_at"]
    )


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT COUNT(*) FROM message_delivery")) or db.scalar(
        sa.text("SELECT COUNT(*) FROM onebot_connection")
    ):
        raise RuntimeError(
            "message data exists; downgrade would destroy delivery/connection history"
        )
    op.drop_table("message_delivery")
    op.drop_table("onebot_connection")

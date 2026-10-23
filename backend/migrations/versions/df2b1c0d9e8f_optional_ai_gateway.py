"""Optional AI configuration and session-bound inert parse requests."""

import sqlalchemy as sa
from alembic import op

revision = "df2b1c0d9e8f"
down_revision = "ce1a0b9c8d7e"
branch_labels = None
depends_on = None


def upgrade():
    config = op.create_table(
        "ai_configuration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_ai_configuration_singleton"),
        sa.CheckConstraint("timeout_seconds BETWEEN 2 AND 20", name="ck_ai_timeout"),
    )
    op.bulk_insert(
        config,
        [
            {
                "id": 1,
                "version": 1,
                "enabled": False,
                "base_url": "",
                "model": "",
                "timeout_seconds": 10,
                "tools": [],
            }
        ],
    )
    op.create_table(
        "ai_request",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column(
            "session_digest", sa.String(64), sa.ForeignKey("session_token.digest"), nullable=False
        ),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_ai_request_owner_key"),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("intent", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('parsing','ready','clarification','failed','cancelled')",
            name="ck_ai_request_state",
        ),
        sa.CheckConstraint(
            "(state IN ('ready','clarification') AND intent IS NOT NULL) OR "
            "(state IN ('parsing','failed','cancelled') AND intent IS NULL)",
            name="ck_ai_request_intent",
        ),
    )
    op.create_index("ix_ai_request_owner_created", "ai_request", ["owner_id", "created_at"])
    op.create_index("ix_ai_request_state_lease", "ai_request", ["state", "lease_expires_at"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM ai_request")):
        raise RuntimeError("AI request history exists; destructive downgrade refused")
    op.drop_table("ai_request")
    op.drop_table("ai_configuration")

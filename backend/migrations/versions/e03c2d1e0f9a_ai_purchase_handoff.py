"""Explicit AI purchase handoff, preserving old request and business schemas."""

import sqlalchemy as sa
from alembic import op

revision = "e03c2d1e0f9a"
down_revision = "df2b1c0d9e8f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_handoff",
        sa.Column("request_id", sa.String(36), sa.ForeignKey("ai_request.id"), primary_key=True),
        sa.Column(
            "operation_id", sa.String(36), sa.ForeignKey("message_operation.id"), nullable=False
        ),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operation_id", name="uq_ai_handoff_operation"),
        sa.CheckConstraint("source_version >= 1", name="ck_ai_handoff_version"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM ai_request")):
        raise RuntimeError(
            "AI request history exists; old intent parser cannot safely read new history"
        )
    op.drop_table("ai_handoff")

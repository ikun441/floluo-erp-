"""message identity and durable inbox"""

import sqlalchemy as sa
from alembic import op

revision = "8b7a6c5d4e3f"
down_revision = "5a6ef43a4a48"
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
        "onebot_instance",
        *row_columns(),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("bot_id", sa.String(20), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "message_binding",
        *row_columns(),
        sa.Column(
            "instance_id", sa.String(36), sa.ForeignKey("onebot_instance.id"), nullable=False
        ),
        sa.Column("platform_user_id", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("instance_id", "platform_user_id"),
        sa.UniqueConstraint("instance_id", "owner_id"),
    )
    op.create_table(
        "binding_challenge",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column(
            "instance_id", sa.String(36), sa.ForeignKey("onebot_instance.id"), nullable=False
        ),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("erp_user.id"), nullable=False),
        sa.Column("platform_user_id", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "message_inbox",
        sa.Column("event_key", sa.String(64), primary_key=True),
        sa.Column(
            "instance_id", sa.String(36), sa.ForeignKey("onebot_instance.id"), nullable=False
        ),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, fields in {
        "message_binding": ["instance_id", "owner_id"],
        "binding_challenge": ["instance_id", "owner_id", "expires_at"],
        "message_inbox": ["instance_id", "processed_at"],
    }.items():
        for field in fields:
            op.create_index("ix_" + table + "_" + field, table, [field])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER message_inbox_immutable BEFORE UPDATE OR DELETE ON message_inbox FOR EACH ROW EXECUTE FUNCTION erp_reject_mutation()"
        )
        op.execute(
            "CREATE TRIGGER message_inbox_no_truncate BEFORE TRUNCATE ON message_inbox FOR EACH STATEMENT EXECUTE FUNCTION erp_reject_mutation()"
        )
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER message_inbox_{action.lower()}_guard BEFORE {action} ON message_inbox BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
            )


def downgrade():
    bind = op.get_bind()
    for table in ("message_inbox", "binding_challenge", "message_binding", "onebot_instance"):
        if bind.scalar(sa.text("SELECT COUNT(*) FROM " + table)):
            raise RuntimeError(
                "message data exists; downgrade would destroy identity or replay history"
            )
    for table in ("message_inbox", "binding_challenge", "message_binding", "onebot_instance"):
        op.drop_table(table)

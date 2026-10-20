"""Initialize authorization gate and protect append-only records."""
from alembic import op
import sqlalchemy as sa

revision = "724dfa42fcdd"
down_revision = "613ceb31ebcc"
branch_labels = None
depends_on = None


def upgrade():
    op.bulk_insert(sa.table("authorization_gate", sa.column("id", sa.Integer())), [{"id": 1}])
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION erp_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'append-only record'; END; $$""")
        for table in ("audit_event", "policy_revision"):
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION erp_reject_mutation()")
            op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION erp_reject_mutation()")
    elif dialect == "sqlite":
        for table in ("audit_event", "policy_revision"):
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only record'); END")


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in ("audit_event", "policy_revision"):
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
            op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        elif dialect == "sqlite":
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER {table}_{action}_guard")
    if dialect == "postgresql":
        op.execute("DROP FUNCTION erp_reject_mutation()")
    op.execute("DELETE FROM authorization_gate")

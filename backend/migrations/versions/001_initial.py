"""Initial governance schema. Snapshot frozen with this migration."""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # The initial schema is kept in a standalone SQL snapshot; later revisions use explicit DDL.
    from pathlib import Path

    sql = (Path(__file__).parents[1] / "001_schema.sql").read_text()
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))


def downgrade():
    for table in [
        "events",
        "reservations",
        "api_keys",
        "budgets",
        "approvals",
        "assets",
        "teams",
        "departments",
        "users",
    ]:
        op.drop_table(table)

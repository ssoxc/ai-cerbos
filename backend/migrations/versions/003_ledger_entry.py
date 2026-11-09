"""Budget ledger inside LiteLLM: record how each call arrived and its final model."""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reservations",
        sa.Column("entry", sa.String(16), nullable=False, server_default="gateway"),
    )
    op.add_column(
        "reservations", sa.Column("model", sa.String(100), nullable=False, server_default="")
    )


def downgrade():
    op.drop_column("reservations", "model")
    op.drop_column("reservations", "entry")

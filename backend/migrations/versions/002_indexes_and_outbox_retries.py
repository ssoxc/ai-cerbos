"""Indexes for hot queries and retry bookkeeping for the event outbox."""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("events", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index(
        "ix_events_outbox",
        "events",
        ["created_at"],
        postgresql_where=sa.text("delivered_at IS NULL AND failed_at IS NULL"),
    )
    op.create_index("ix_reservations_key_created", "reservations", ["key_id", "created_at"])
    op.create_index("ix_approvals_resource_status", "approvals", ["resource_id", "status"])
    op.create_index("ix_api_keys_asset_id", "api_keys", ["asset_id"])


def downgrade():
    op.drop_index("ix_api_keys_asset_id", table_name="api_keys")
    op.drop_index("ix_approvals_resource_status", table_name="approvals")
    op.drop_index("ix_reservations_key_created", table_name="reservations")
    op.drop_index("ix_events_outbox", table_name="events")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_column("events", "failed_at")
    op.drop_column("events", "attempts")

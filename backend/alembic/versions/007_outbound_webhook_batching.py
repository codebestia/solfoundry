"""Add outbound_webhook_queue and outbound_webhook_logs tables.

Revision ID: 007_outbound_webhook_batching
Revises: 006_add_anti_sybil_tables
Create Date: 2026-03-23
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_outbound_webhook_batching"
down_revision: Union[str, None] = "006_add_anti_sybil_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # outbound_webhook_queue
    op.create_table(
        "outbound_webhook_queue",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_outbound_webhook_queue_user_id", "outbound_webhook_queue", ["user_id"])
    op.create_index("ix_outbound_webhook_queue_processed", "outbound_webhook_queue", ["processed"])
    op.create_index("ix_outbound_webhook_queue_created_at", "outbound_webhook_queue", ["created_at"])

    # outbound_webhook_logs
    op.create_table(
        "outbound_webhook_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "webhook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contributor_webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_code", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_outbound_webhook_logs_webhook_id", "outbound_webhook_logs", ["webhook_id"])
    op.create_index("ix_outbound_webhook_logs_batch_id", "outbound_webhook_logs", ["batch_id"])
    op.create_index("ix_outbound_webhook_logs_delivered_at", "outbound_webhook_logs", ["delivered_at"])

def downgrade() -> None:
    op.drop_table("outbound_webhook_logs")
    op.drop_table("outbound_webhook_queue")

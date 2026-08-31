"""add chat_sessions.channel to split AI and live conversations

A customer's AI thread and their live-Sale thread are separate rows from here on, so a
Sale can never be handed the AI history: `sale_live` resolves LIVE rows only.

Existing rows backfill to 'ai' — every session created before this migration was the
single combined thread, and the customer-facing AI page is the one that must keep it.
A session sitting in a live handoff at upgrade time is additionally flipped to 'live':
its Sale is mid-conversation, and that claim is what the live inbox has to keep finding.

Revision ID: a1b2c3d4e5f7
Revises: b8c9d0e1f2a3
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("channel", sa.String(length=10), nullable=False, server_default="ai"),
    )
    op.create_index("ix_chat_sessions_channel", "chat_sessions", ["channel"])
    op.execute("UPDATE chat_sessions SET channel = 'live' WHERE status IN ('waiting_sale', 'sale_handling')")


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_channel", table_name="chat_sessions")
    op.drop_column("chat_sessions", "channel")

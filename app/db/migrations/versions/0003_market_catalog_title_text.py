"""widen market catalog title fields

Revision ID: 0003_market_catalog_title_text
Revises: 0002_monitor_events
Create Date: 2026-04-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_market_catalog_title_text"
down_revision = "0002_monitor_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "market_catalog",
        "title",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "market_catalog",
        "subtitle",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "market_catalog",
        "subtitle",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
        postgresql_using="left(subtitle, 512)",
    )
    op.alter_column(
        "market_catalog",
        "title",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=False,
        postgresql_using="left(title, 512)",
    )

"""add document.source_path for directory sync

Revision ID: a1c2e3f40567
Revises: b035cf4fc76e
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c2e3f40567"
down_revision: str | None = "b035cf4fc76e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("source_path", sa.String(length=1024), nullable=True))
    op.create_index("ix_document_source_path", "document", ["source_path"])


def downgrade() -> None:
    op.drop_index("ix_document_source_path", table_name="document")
    op.drop_column("document", "source_path")

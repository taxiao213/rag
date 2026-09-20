"""add chunk search_vector tsvector

Revision ID: e03f81bdbef0
Revises: 6d79dbeae11d
Create Date: 2026-09-20
"""

from alembic import op

revision: str = 'e03f81bdbef0'
down_revision: str | None = '6d79dbeae11d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BM25 检索字段：bigram 化 content 的 tsvector（见 indexing/bm25_store.py）
    op.execute("ALTER TABLE chunk ADD COLUMN search_vector tsvector")
    op.execute("CREATE INDEX ix_chunk_search_vector ON chunk USING gin(search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_search_vector")
    op.execute("ALTER TABLE chunk DROP COLUMN IF EXISTS search_vector")

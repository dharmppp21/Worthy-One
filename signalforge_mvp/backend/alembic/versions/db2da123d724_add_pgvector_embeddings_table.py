"""Add pgvector embeddings table

Revision ID: db2da123d724
Revises: 8cea4b9cd539
Create Date: 2026-06-26 21:19:06.281138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db2da123d724'
down_revision: Union[str, Sequence[str], None] = '8cea4b9cd539'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create pgvector extension and embeddings table (PostgreSQL only)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create embeddings table for semantic search. The pgvector `vector` type is
    # not a core SQLAlchemy type, so the embedding column is added via raw SQL
    # after the table is created.
    op.create_table(
        "embeddings",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Index("idx_embeddings_entity", "entity_type", "entity_id"),
    )
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(1536)")
    # Add unique constraint for UPSERT
    op.create_unique_constraint("uq_embeddings_entity", "embeddings", ["entity_type", "entity_id"])


def downgrade() -> None:
    """Downgrade schema — drop embeddings table and pgvector extension (PostgreSQL only)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_constraint("uq_embeddings_entity", "embeddings", type_="unique")
    op.drop_table("embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")

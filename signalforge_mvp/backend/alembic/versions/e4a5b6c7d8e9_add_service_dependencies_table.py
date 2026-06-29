"""Add service_dependencies table

Revision ID: e4a5b6c7d8e9
Revises: db2da123d724
Create Date: 2026-06-29 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'db2da123d724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create service_dependencies table."""
    op.create_table(
        'service_dependencies',
        sa.Column('id', sa.String(length=128), nullable=False),
        sa.Column('source_service_id', sa.String(length=128), nullable=False),
        sa.Column('target_service_id', sa.String(length=128), nullable=False),
        sa.Column('dependency_type', sa.String(length=128), nullable=False, server_default='unknown'),
        sa.Column('connection_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('avg_latency_ms', sa.Float(), nullable=True),
        sa.Column('error_rate', sa.Float(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('discovery_sources', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('tenant_id', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_dep_source_target', 'service_dependencies', ['source_service_id', 'target_service_id'], unique=False)
    op.create_index(op.f('ix_service_dependencies_source_service_id'), 'service_dependencies', ['source_service_id'], unique=False)
    op.create_index(op.f('ix_service_dependencies_target_service_id'), 'service_dependencies', ['target_service_id'], unique=False)
    op.create_index(op.f('ix_service_dependencies_tenant_id'), 'service_dependencies', ['tenant_id'], unique=False)


def downgrade() -> None:
    """Drop service_dependencies table."""
    op.drop_index(op.f('ix_service_dependencies_tenant_id'), table_name='service_dependencies')
    op.drop_index(op.f('ix_service_dependencies_target_service_id'), table_name='service_dependencies')
    op.drop_index(op.f('ix_service_dependencies_source_service_id'), table_name='service_dependencies')
    op.drop_index('idx_dep_source_target', table_name='service_dependencies')
    op.drop_table('service_dependencies')

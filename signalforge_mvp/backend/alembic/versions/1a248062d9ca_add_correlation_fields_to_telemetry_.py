"""add correlation fields to telemetry_events

Revision ID: 1a248062d9ca
Revises: e4a5b6c7d8e9
Create Date: 2026-06-30 15:57:11.790198

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a248062d9ca'
down_revision: Union[str, Sequence[str], None] = 'e4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('telemetry_events') as batch_op:
        # Make tenant_id and service_name nullable
        batch_op.alter_column('tenant_id', existing_type=sa.String(length=128), nullable=True)
        batch_op.alter_column('service_name', existing_type=sa.String(length=128), nullable=True)
        # Add correlation_metadata JSON column
        batch_op.add_column(sa.Column('correlation_metadata', sa.JSON(), nullable=True))
        # Add uncorrelated boolean column with index
        batch_op.add_column(sa.Column('uncorrelated', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('idx_events_uncorrelated_tenant', 'telemetry_events', ['uncorrelated', 'tenant_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_events_uncorrelated_tenant', table_name='telemetry_events')
    with op.batch_alter_table('telemetry_events') as batch_op:
        batch_op.drop_column('uncorrelated')
        batch_op.drop_column('correlation_metadata')
        batch_op.alter_column('service_name', existing_type=sa.String(length=128), nullable=False)
        batch_op.alter_column('tenant_id', existing_type=sa.String(length=128), nullable=False)

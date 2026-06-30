"""Add service_health table and health_status column

Revision ID: f4ec68247c38
Revises: e4a5b6c7d8e9
Create Date: 2026-07-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4ec68247c38"
down_revision: Union[str, None] = "1a248062d9ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    # Add health_status column to discovered_services if table exists
    if "discovered_services" in inspector.get_table_names():
        with op.batch_alter_table("discovered_services") as batch_op:
            batch_op.add_column(
                sa.Column("health_status", sa.String(32), nullable=True)
            )

    # Create service_health table
    if "service_health" not in inspector.get_table_names():
        op.create_table(
            "service_health",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("service_id", sa.String(128), nullable=False, index=True),
            sa.Column("status", sa.String(32), nullable=False, default="unknown"),
            sa.Column("probe_results", sa.JSON, nullable=False, default=list),
            sa.Column("last_probed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_up_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_down_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("uptime_percentage", sa.Float, nullable=False, default=100.0),
            sa.Column("tenant_id", sa.String(128), nullable=True, index=True),
            sa.Index("idx_health_service_probed", "service_id", "last_probed_at"),
        )


def downgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    if "service_health" in inspector.get_table_names():
        op.drop_table("service_health")

    if "discovered_services" in inspector.get_table_names():
        with op.batch_alter_table("discovered_services") as batch_op:
            batch_op.drop_column("health_status")

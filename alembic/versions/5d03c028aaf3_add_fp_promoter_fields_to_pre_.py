"""add fp promoter fields to pre_influencers

Revision ID: 5d03c028aaf3
Revises: 4ba999b9c879
Create Date: 2025-12-22 02:10:58.868710

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d03c028aaf3'
down_revision: Union[str, Sequence[str], None] = '4ba999b9c879'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("pre_influencers")}
    if "fp_promoter_id" not in existing_cols:
        op.add_column("pre_influencers", sa.Column("fp_promoter_id", sa.String(), nullable=True))
    if "fp_ref_id" not in existing_cols:
        op.add_column("pre_influencers", sa.Column("fp_ref_id", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("pre_influencers", "fp_ref_id")
    op.drop_column("pre_influencers", "fp_promoter_id")

"""add firstpromoter fields to influencers

Revision ID: 05e2844dfdc9
Revises: 1153b75ea876
Create Date: 2025-12-23 08:06:29.514563

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05e2844dfdc9'
down_revision: Union[str, Sequence[str], None] = '1153b75ea876'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("influencers", sa.Column("fp_promoter_id", sa.String(), nullable=True))
    op.add_column("influencers", sa.Column("fp_ref_id", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("influencers", "fp_ref_id")
    op.drop_column("influencers", "fp_promoter_id")

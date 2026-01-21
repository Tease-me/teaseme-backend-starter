"""make influencer email required and unique

Revision ID: ea7a1d780a7b
Revises: 1e0c023e32c6
Create Date: 2026-01-21 23:30:14.743412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea7a1d780a7b'
down_revision: Union[str, Sequence[str], None] = '1e0c023e32c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column(
        "influencers",
        "email",
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_influencers_email",
        "influencers",
        ["email"],
    )


def downgrade():
    op.drop_constraint(
        "uq_influencers_email",
        "influencers",
        type_="unique",
    )
    op.alter_column(
        "influencers",
        "email",
        nullable=True,
    )

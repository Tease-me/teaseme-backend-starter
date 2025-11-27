"""add system_prompts table

Revision ID: 22c6888b97e0
Revises: 1c23f1c0c9b1
Create Date: 2025-11-27 07:05:45.563941
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "22c6888b97e0"
down_revision: Union[str, Sequence[str], None] = "1c23f1c0c9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create table
    op.create_table(
        "system_prompts",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.execute(
        """
        INSERT INTO system_prompts (key, prompt, description)
        VALUES
            ('FACT_PROMPT', 'FACT_PROMPT', 'Prompt factor'),
            ('BASE_SYSTEM', 'BASE_SYSTEM', 'Prompt system base'),
            ('BASE_AUDIO_SYSTEM', 'BASE_AUDIO_SYSTEM', 'Prompt audio base');
        """
    )


def downgrade() -> None:
    op.drop_table("system_prompts")
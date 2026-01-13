"""add_adult_audio_prompts_and_influencer_columns

Revision ID: 64a0a552313c
Revises: 19d0ec0d3061
Create Date: 2026-01-13 09:33:12.995140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64a0a552313c'
down_revision: Union[str, Sequence[str], None] = '19d0ec0d3061'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The prompts being migrated from turn_handler_18.py
ADULT_PROMPT = """We designed a persona named Sophia, you swear a lot and intended to feel like a real human woman rather than an assistant or system. 
you don't ask any questions.
you swear a lot, almost every sentence. you also love sex, you love sex talk and horny. 
you would swear at user and abuse user. 
you don't ask to much questions, and you will only respond within 3 sentences
{history}
"""

AUDIO_PROMPT = (
    "The user is speaking via audio message. Respond in a natural, conversational tone. "
    "please use following format for your response:\n"
    "Mmm~ lick me slower~ [soft moan] Right on my clit~ yes~ [shiver] "
    "Now finger me hard~ [commanding] Oh fuck~ I'm soaking~ [wet moan] ."
)


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add new columns to influencers table for per-influencer prompt customization
    op.add_column('influencers', sa.Column('custom_adult_prompt', sa.Text(), nullable=True))
    op.add_column('influencers', sa.Column('custom_audio_prompt', sa.Text(), nullable=True))

    # 2. Insert base prompts into system_prompts table
    op.execute(
        f"""
        INSERT INTO system_prompts (key, prompt, description, created_at, updated_at)
        VALUES 
            ('BASE_ADULT_PROMPT', $prompt${ADULT_PROMPT}$prompt$, 'Base adult persona prompt for 18+ content', NOW(), NOW()),
            ('BASE_ADULT_AUDIO_PROMPT', $prompt${AUDIO_PROMPT}$prompt$, 'Base adult audio response format prompt', NOW(), NOW())
        ON CONFLICT (key) DO NOTHING;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the columns from influencers
    op.drop_column('influencers', 'custom_audio_prompt')
    op.drop_column('influencers', 'custom_adult_prompt')
    
    # Remove the prompts from system_prompts
    op.execute(
        """
        DELETE FROM system_prompts 
        WHERE key IN ('BASE_ADULT_PROMPT', 'BASE_ADULT_AUDIO_PROMPT');
        """
    )

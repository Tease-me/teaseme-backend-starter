"""replace voice_prompt with bio_json

Revision ID: 19c7cf7032c9
Revises: c692d0098e19
Create Date: 2025-12-17 00:28:47.840348
"""
from alembic import op
import sqlalchemy as sa

revision = "19c7cf7032c9"
down_revision = "c692d0098e19"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("influencers")}

    # 1) Add bio_json if missing (JSON column)
    if "bio_json" not in cols:
        op.add_column("influencers", sa.Column("bio_json", sa.JSON(), nullable=True))

    # refresh columns after add
    cols = {c["name"] for c in insp.get_columns("influencers")}

    # 2) Migrate old voice_prompt into bio_json and drop voice_prompt
    if "voice_prompt" in cols:
        # ✅ Works even if bio_json is type JSON (not JSONB)
        op.execute("""
            UPDATE influencers
            SET bio_json = (
                COALESCE(bio_json::jsonb, '{}'::jsonb)
                || jsonb_build_object('voice_prompt', voice_prompt)
            )::json
            WHERE voice_prompt IS NOT NULL
        """)
        op.drop_column("influencers", "voice_prompt")


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("influencers")}

    if "voice_prompt" not in cols:
        op.add_column("influencers", sa.Column("voice_prompt", sa.String(), nullable=True))

    cols = {c["name"] for c in insp.get_columns("influencers")}

    if "bio_json" in cols:
        op.drop_column("influencers", "bio_json")
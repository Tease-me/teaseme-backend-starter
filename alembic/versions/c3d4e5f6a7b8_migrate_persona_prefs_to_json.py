"""migrate persona preferences to json column

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-09 14:25:00.000000+10:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from psycopg2.extras import Json

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("preferences_json", JSONB, nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT influencer_id, preference_key, liked "
            "FROM persona_preferences ORDER BY influencer_id"
        )
    ).fetchall()

    prefs: dict[str, dict] = {}
    for influencer_id, key, liked in rows:
        prefs.setdefault(influencer_id, {})[key] = liked

    for influencer_id, pref_dict in prefs.items():
        conn.execute(
            sa.text(
                "UPDATE influencers SET preferences_json = :prefs WHERE id = :iid"
            ),
            {"prefs": Json(pref_dict), "iid": influencer_id},
        )

    op.drop_index("ix_persona_pref_infl", table_name="persona_preferences")
    op.drop_table("persona_preferences")


def downgrade() -> None:
    op.create_table(
        "persona_preferences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("influencer_id", sa.String, sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preference_key", sa.String, sa.ForeignKey("preference_catalog.key", ondelete="CASCADE"), nullable=False),
        sa.Column("liked", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_persona_pref_infl", "persona_preferences", ["influencer_id"])

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, preferences_json FROM influencers WHERE preferences_json IS NOT NULL")
    ).fetchall()

    for influencer_id, pref_dict in rows:
        if not isinstance(pref_dict, dict):
            continue
        for key, liked in pref_dict.items():
            conn.execute(
                sa.text(
                    "INSERT INTO persona_preferences (influencer_id, preference_key, liked) "
                    "VALUES (:iid, :key, :liked)"
                ),
                {"iid": influencer_id, "key": key, "liked": liked},
            )

    op.drop_column("influencers", "preferences_json")

"""add_preference_catalog_system

Revision ID: a1b2c3d4e5f6
Revises: d4e5f6a7b8c9
Create Date: 2026-02-09 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Seed data ───────────────────────────────────────────────────
PREFERENCE_ITEMS = [
    # food_and_drink
    ("food_sushi", "food_and_drink", "Sushi", "🍣", 1),
    ("food_coffee", "food_and_drink", "Coffee", "☕", 2),
    ("food_wine", "food_and_drink", "Wine", "🍷", 3),
    ("food_cooking", "food_and_drink", "Cooking at home", "🍳", 4),
    ("food_vegan", "food_and_drink", "Vegan food", "🥗", 5),
    ("food_fastfood", "food_and_drink", "Fast food", "🍔", 6),
    ("food_brunch", "food_and_drink", "Brunch", "🥞", 7),
    # music_and_entertainment
    ("ent_pop", "music_and_entertainment", "Pop music", "🎵", 1),
    ("ent_hiphop", "music_and_entertainment", "Hip-hop / R&B", "🎤", 2),
    ("ent_horror", "music_and_entertainment", "Horror movies", "👻", 3),
    ("ent_reality_tv", "music_and_entertainment", "Reality TV", "📺", 4),
    ("ent_gaming", "music_and_entertainment", "Gaming", "🎮", 5),
    ("ent_anime", "music_and_entertainment", "Anime", "🎌", 6),
    ("ent_concerts", "music_and_entertainment", "Live concerts", "🎶", 7),
    # fashion_and_style
    ("style_streetwear", "fashion_and_style", "Streetwear", "👟", 1),
    ("style_designer", "fashion_and_style", "Designer brands", "👜", 2),
    ("style_minimalist", "fashion_and_style", "Minimalist style", "🤍", 3),
    ("style_jewelry", "fashion_and_style", "Jewelry & Accessories", "💍", 4),
    ("style_sneakers", "fashion_and_style", "Sneakers", "👠", 5),
    ("style_thrifting", "fashion_and_style", "Thrifting", "🛍️", 6),
    ("style_matching", "fashion_and_style", "Matching outfits", "👫", 7),
    # hobbies_and_interests
    ("hobby_gym", "hobbies_and_interests", "Gym / Fitness", "💪", 1),
    ("hobby_reading", "hobbies_and_interests", "Reading", "📚", 2),
    ("hobby_traveling", "hobbies_and_interests", "Traveling", "✈️", 3),
    ("hobby_skincare", "hobbies_and_interests", "Skincare & Beauty", "✨", 4),
    ("hobby_photography", "hobbies_and_interests", "Photography", "📷", 5),
    ("hobby_art", "hobbies_and_interests", "Art & Painting", "🎨", 6),
    ("hobby_yoga", "hobbies_and_interests", "Yoga & Meditation", "🧘", 7),
    # social_and_lifestyle
    ("social_partying", "social_and_lifestyle", "Partying / Nightlife", "🎉", 1),
    ("social_cozy_nights", "social_and_lifestyle", "Cozy nights in", "🕯️", 2),
    ("social_early_mornings", "social_and_lifestyle", "Early mornings", "🌅", 3),
    ("social_pets", "social_and_lifestyle", "Pets & Animals", "🐶", 4),
    ("social_cooking_together", "social_and_lifestyle", "Cooking together", "👩‍🍳", 5),
    ("social_roadtrips", "social_and_lifestyle", "Road trips", "🚗", 6),
    ("social_beach", "social_and_lifestyle", "Beach days", "🏖️", 7),
    # romance_and_dating
    ("romance_texting_first", "romance_and_dating", "Texting first", "💬", 1),
    ("romance_surprises", "romance_and_dating", "Surprise dates", "🎁", 2),
    ("romance_pda", "romance_and_dating", "Public affection (PDA)", "💏", 3),
    ("romance_long_walks", "romance_and_dating", "Long walks", "🚶", 4),
    ("romance_planning", "romance_and_dating", "Planning dates ahead", "📋", 5),
    ("romance_spontaneous", "romance_and_dating", "Spontaneous plans", "⚡", 6),
    ("romance_love_notes", "romance_and_dating", "Love letters & Notes", "💌", 7),
    # values_and_personality
    ("value_ambition", "values_and_personality", "Ambition", "🚀", 1),
    ("value_loyalty", "values_and_personality", "Loyalty", "🤝", 2),
    ("value_humor", "values_and_personality", "Sense of humor", "😂", 3),
    ("value_independence", "values_and_personality", "Independence", "🦅", 4),
    ("value_deep_convos", "values_and_personality", "Deep conversations", "💭", 5),
    ("value_honesty", "values_and_personality", "Honesty", "💯", 6),
    ("value_vulnerability", "values_and_personality", "Vulnerability", "🥺", 7),
    # aesthetics_and_vibes
    ("vibe_beach", "aesthetics_and_vibes", "Beach & Ocean", "🌊", 1),
    ("vibe_mountains", "aesthetics_and_vibes", "Mountains", "🏔️", 2),
    ("vibe_city", "aesthetics_and_vibes", "City life", "🌆", 3),
    ("vibe_cottagecore", "aesthetics_and_vibes", "Cozy / Cottagecore", "🏡", 4),
    ("vibe_luxury", "aesthetics_and_vibes", "Luxury", "💎", 5),
    ("vibe_sunsets", "aesthetics_and_vibes", "Sunsets", "🌇", 6),
    ("vibe_rainy_days", "aesthetics_and_vibes", "Rainy days", "🌧️", 7),
    # pet_peeves
    ("peeve_late_replies", "pet_peeves", "Late replies", "⏰", 1),
    ("peeve_bad_hygiene", "pet_peeves", "Bad hygiene", "🚿", 2),
    ("peeve_rudeness", "pet_peeves", "Rudeness", "😤", 3),
    ("peeve_interrupting", "pet_peeves", "Being interrupted", "🤐", 4),
    ("peeve_ghosting", "pet_peeves", "Ghosting", "👀", 5),
    ("peeve_jealousy", "pet_peeves", "Jealousy", "💚", 6),
    ("peeve_dishonesty", "pet_peeves", "Dishonesty", "🤥", 7),
    # tech_and_culture
    ("culture_tiktok", "tech_and_culture", "TikTok", "📱", 1),
    ("culture_memes", "tech_and_culture", "Memes", "😜", 2),
    ("culture_podcasts", "tech_and_culture", "Podcasts", "🎧", 3),
    ("culture_social_media", "tech_and_culture", "Social media", "📲", 4),
    ("culture_true_crime", "tech_and_culture", "True crime", "🔍", 5),
    ("culture_astrology", "tech_and_culture", "Astrology", "♈", 6),
    ("culture_self_improvement", "tech_and_culture", "Self-improvement", "📈", 7),
]


def upgrade() -> None:
    """Create preference tables and seed catalog."""

    # 1. preference_catalog
    op.create_table(
        "preference_catalog",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("category", sa.String(), nullable=False, index=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("emoji", sa.String(), nullable=True),

        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )

    # 2. persona_preferences
    op.create_table(
        "persona_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("influencer_id", sa.String(), sa.ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("preference_key", sa.String(), sa.ForeignKey("preference_catalog.key", ondelete="CASCADE"), nullable=False),
        sa.Column("liked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("influencer_id", "preference_key", name="uq_persona_pref"),
    )
    op.create_index("ix_persona_pref_infl", "persona_preferences", ["influencer_id"])

    # 3. user_preferences
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("preference_key", sa.String(), sa.ForeignKey("preference_catalog.key", ondelete="CASCADE"), nullable=False),
        sa.Column("liked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "preference_key", name="uq_user_pref"),
    )
    op.create_index("ix_user_pref_user", "user_preferences", ["user_id"])

    # 4. Seed catalog
    catalog = sa.table(
        "preference_catalog",
        sa.column("key", sa.String),
        sa.column("category", sa.String),
        sa.column("label", sa.String),
        sa.column("emoji", sa.String),
        sa.column("display_order", sa.Integer),
    )
    op.bulk_insert(catalog, [
        {
            "key": k, "category": cat, "label": lbl,
            "emoji": emo, "display_order": do,
        }
        for k, cat, lbl, emo, do in PREFERENCE_ITEMS
    ])


def downgrade() -> None:
    """Drop preference tables."""
    op.drop_table("user_preferences")
    op.drop_table("persona_preferences")
    op.drop_table("preference_catalog")

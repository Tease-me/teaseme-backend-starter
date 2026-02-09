"""
Preference Catalog — Master list of ~70 like/dislike items.

Each entry:
  key              — unique identifier (snake_case: category_item)
  category         — grouping key
  label            — human-readable name
  emoji            — for future UI
  display_order    — ordering within category
"""

PREFERENCE_ITEMS: list[dict] = [
    # ── food_and_drink ──────────────────────────────────────────
    {"key": "food_sushi",           "category": "food_and_drink",        "label": "Sushi",               "emoji": "🍣", "display_order": 1},
    {"key": "food_coffee",          "category": "food_and_drink",        "label": "Coffee",              "emoji": "☕", "display_order": 2},
    {"key": "food_wine",            "category": "food_and_drink",        "label": "Wine",                "emoji": "🍷", "display_order": 3},
    {"key": "food_cooking",         "category": "food_and_drink",        "label": "Cooking at home",     "emoji": "🍳", "display_order": 4},
    {"key": "food_vegan",           "category": "food_and_drink",        "label": "Vegan food",          "emoji": "🥗", "display_order": 5},
    {"key": "food_fastfood",        "category": "food_and_drink",        "label": "Fast food",           "emoji": "🍔", "display_order": 6},
    {"key": "food_brunch",          "category": "food_and_drink",        "label": "Brunch",              "emoji": "🥞", "display_order": 7},

    # ── music_and_entertainment ─────────────────────────────────
    {"key": "ent_pop",              "category": "music_and_entertainment","label": "Pop music",           "emoji": "🎵", "display_order": 1},
    {"key": "ent_hiphop",           "category": "music_and_entertainment","label": "Hip-hop / R&B",      "emoji": "🎤", "display_order": 2},
    {"key": "ent_horror",           "category": "music_and_entertainment","label": "Horror movies",       "emoji": "👻", "display_order": 3},
    {"key": "ent_reality_tv",       "category": "music_and_entertainment","label": "Reality TV",          "emoji": "📺", "display_order": 4},
    {"key": "ent_gaming",           "category": "music_and_entertainment","label": "Gaming",              "emoji": "🎮", "display_order": 5},
    {"key": "ent_anime",            "category": "music_and_entertainment","label": "Anime",               "emoji": "🎌", "display_order": 6},
    {"key": "ent_concerts",         "category": "music_and_entertainment","label": "Live concerts",       "emoji": "🎶", "display_order": 7},

    # ── fashion_and_style ───────────────────────────────────────
    {"key": "style_streetwear",     "category": "fashion_and_style",     "label": "Streetwear",          "emoji": "👟", "display_order": 1},
    {"key": "style_designer",       "category": "fashion_and_style",     "label": "Designer brands",     "emoji": "👜", "display_order": 2},
    {"key": "style_minimalist",     "category": "fashion_and_style",     "label": "Minimalist style",    "emoji": "🤍", "display_order": 3},
    {"key": "style_jewelry",        "category": "fashion_and_style",     "label": "Jewelry & Accessories","emoji": "💍", "display_order": 4},
    {"key": "style_sneakers",       "category": "fashion_and_style",     "label": "Sneakers",            "emoji": "👠", "display_order": 5},
    {"key": "style_thrifting",      "category": "fashion_and_style",     "label": "Thrifting",           "emoji": "🛍️", "display_order": 6},
    {"key": "style_matching",       "category": "fashion_and_style",     "label": "Matching outfits",    "emoji": "👫", "display_order": 7},

    # ── hobbies_and_interests ───────────────────────────────────
    {"key": "hobby_gym",            "category": "hobbies_and_interests", "label": "Gym / Fitness",       "emoji": "💪", "display_order": 1},
    {"key": "hobby_reading",        "category": "hobbies_and_interests", "label": "Reading",             "emoji": "📚", "display_order": 2},
    {"key": "hobby_traveling",      "category": "hobbies_and_interests", "label": "Traveling",           "emoji": "✈️", "display_order": 3},
    {"key": "hobby_skincare",       "category": "hobbies_and_interests", "label": "Skincare & Beauty",   "emoji": "✨", "display_order": 4},
    {"key": "hobby_photography",    "category": "hobbies_and_interests", "label": "Photography",         "emoji": "📷", "display_order": 5},
    {"key": "hobby_art",            "category": "hobbies_and_interests", "label": "Art & Painting",      "emoji": "🎨", "display_order": 6},
    {"key": "hobby_yoga",           "category": "hobbies_and_interests", "label": "Yoga & Meditation",   "emoji": "🧘", "display_order": 7},

    # ── social_and_lifestyle ────────────────────────────────────
    {"key": "social_partying",      "category": "social_and_lifestyle",  "label": "Partying / Nightlife","emoji": "🎉", "display_order": 1},
    {"key": "social_cozy_nights",   "category": "social_and_lifestyle",  "label": "Cozy nights in",      "emoji": "🕯️", "display_order": 2},
    {"key": "social_early_mornings","category": "social_and_lifestyle",  "label": "Early mornings",       "emoji": "🌅", "display_order": 3},
    {"key": "social_pets",          "category": "social_and_lifestyle",  "label": "Pets & Animals",       "emoji": "🐶", "display_order": 4},
    {"key": "social_cooking_together","category": "social_and_lifestyle","label": "Cooking together",     "emoji": "👩‍🍳", "display_order": 5},
    {"key": "social_roadtrips",     "category": "social_and_lifestyle",  "label": "Road trips",           "emoji": "🚗", "display_order": 6},
    {"key": "social_beach",         "category": "social_and_lifestyle",  "label": "Beach days",           "emoji": "🏖️", "display_order": 7},

    # ── romance_and_dating ──────────────────────────────────────
    {"key": "romance_texting_first","category": "romance_and_dating",    "label": "Texting first",        "emoji": "💬", "display_order": 1},
    {"key": "romance_surprises",    "category": "romance_and_dating",    "label": "Surprise dates",       "emoji": "🎁", "display_order": 2},
    {"key": "romance_pda",          "category": "romance_and_dating",    "label": "Public affection (PDA)","emoji": "💏", "display_order": 3},
    {"key": "romance_long_walks",   "category": "romance_and_dating",    "label": "Long walks",           "emoji": "🚶", "display_order": 4},
    {"key": "romance_planning",     "category": "romance_and_dating",    "label": "Planning dates ahead", "emoji": "📋", "display_order": 5},
    {"key": "romance_spontaneous",  "category": "romance_and_dating",    "label": "Spontaneous plans",    "emoji": "⚡", "display_order": 6},
    {"key": "romance_love_notes",   "category": "romance_and_dating",    "label": "Love letters & Notes", "emoji": "💌", "display_order": 7},

    # ── values_and_personality ──────────────────────────────────
    {"key": "value_ambition",       "category": "values_and_personality","label": "Ambition",             "emoji": "🚀", "display_order": 1},
    {"key": "value_loyalty",        "category": "values_and_personality","label": "Loyalty",              "emoji": "🤝", "display_order": 2},
    {"key": "value_humor",          "category": "values_and_personality","label": "Sense of humor",       "emoji": "😂", "display_order": 3},
    {"key": "value_independence",   "category": "values_and_personality","label": "Independence",         "emoji": "🦅", "display_order": 4},
    {"key": "value_deep_convos",    "category": "values_and_personality","label": "Deep conversations",   "emoji": "💭", "display_order": 5},
    {"key": "value_honesty",        "category": "values_and_personality","label": "Honesty",              "emoji": "💯", "display_order": 6},
    {"key": "value_vulnerability",  "category": "values_and_personality","label": "Vulnerability",        "emoji": "🥺", "display_order": 7},

    # ── aesthetics_and_vibes ────────────────────────────────────
    {"key": "vibe_beach",           "category": "aesthetics_and_vibes",  "label": "Beach & Ocean",        "emoji": "🌊", "display_order": 1},
    {"key": "vibe_mountains",       "category": "aesthetics_and_vibes",  "label": "Mountains",            "emoji": "🏔️", "display_order": 2},
    {"key": "vibe_city",            "category": "aesthetics_and_vibes",  "label": "City life",            "emoji": "🌆", "display_order": 3},
    {"key": "vibe_cottagecore",     "category": "aesthetics_and_vibes",  "label": "Cozy / Cottagecore",   "emoji": "🏡", "display_order": 4},
    {"key": "vibe_luxury",          "category": "aesthetics_and_vibes",  "label": "Luxury",               "emoji": "💎", "display_order": 5},
    {"key": "vibe_sunsets",         "category": "aesthetics_and_vibes",  "label": "Sunsets",              "emoji": "🌇", "display_order": 6},
    {"key": "vibe_rainy_days",      "category": "aesthetics_and_vibes",  "label": "Rainy days",           "emoji": "🌧️", "display_order": 7},

    # ── pet_peeves ──────────────────────────────────────────────
    {"key": "peeve_late_replies",   "category": "pet_peeves",            "label": "Late replies",         "emoji": "⏰", "display_order": 1},
    {"key": "peeve_bad_hygiene",    "category": "pet_peeves",            "label": "Bad hygiene",          "emoji": "🚿", "display_order": 2},
    {"key": "peeve_rudeness",       "category": "pet_peeves",            "label": "Rudeness",             "emoji": "😤", "display_order": 3},
    {"key": "peeve_interrupting",   "category": "pet_peeves",            "label": "Being interrupted",    "emoji": "🤐", "display_order": 4},
    {"key": "peeve_ghosting",       "category": "pet_peeves",            "label": "Ghosting",             "emoji": "👀", "display_order": 5},
    {"key": "peeve_jealousy",       "category": "pet_peeves",            "label": "Jealousy",             "emoji": "💚", "display_order": 6},
    {"key": "peeve_dishonesty",     "category": "pet_peeves",            "label": "Dishonesty",           "emoji": "🤥", "display_order": 7},

    # ── tech_and_culture ────────────────────────────────────────
    {"key": "culture_tiktok",       "category": "tech_and_culture",      "label": "TikTok",               "emoji": "📱", "display_order": 1},
    {"key": "culture_memes",        "category": "tech_and_culture",      "label": "Memes",                "emoji": "😜", "display_order": 2},
    {"key": "culture_podcasts",     "category": "tech_and_culture",      "label": "Podcasts",             "emoji": "🎧", "display_order": 3},
    {"key": "culture_social_media", "category": "tech_and_culture",      "label": "Social media",         "emoji": "📲", "display_order": 4},
    {"key": "culture_true_crime",   "category": "tech_and_culture",      "label": "True crime",           "emoji": "🔍", "display_order": 5},
    {"key": "culture_astrology",    "category": "tech_and_culture",      "label": "Astrology",            "emoji": "♈", "display_order": 6},
    {"key": "culture_self_improvement","category": "tech_and_culture",   "label": "Self-improvement",     "emoji": "📈", "display_order": 7},
]

# Category display metadata
CATEGORIES: dict[str, dict] = {
    "food_and_drink":        {"label": "Food & Drink",          "emoji": "🍽️", "order": 1},
    "music_and_entertainment":{"label": "Music & Entertainment", "emoji": "🎬", "order": 2},
    "fashion_and_style":     {"label": "Fashion & Style",       "emoji": "👗", "order": 3},
    "hobbies_and_interests": {"label": "Hobbies & Interests",   "emoji": "🎯", "order": 4},
    "social_and_lifestyle":  {"label": "Social & Lifestyle",    "emoji": "🌟", "order": 5},
    "romance_and_dating":    {"label": "Romance & Dating",      "emoji": "💕", "order": 6},
    "values_and_personality": {"label": "Values & Personality",  "emoji": "💎", "order": 7},
    "aesthetics_and_vibes":  {"label": "Aesthetics & Vibes",    "emoji": "🎨", "order": 8},
    "pet_peeves":            {"label": "Pet Peeves",            "emoji": "😒", "order": 9},
    "tech_and_culture":      {"label": "Tech & Culture",        "emoji": "📱", "order": 10},
}

# Handy lookup for key validation
ALL_KEYS: set[str] = {item["key"] for item in PREFERENCE_ITEMS}

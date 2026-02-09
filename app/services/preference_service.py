"""Preference Service — core logic for the like/dislike preference system."""
import hashlib
import logging
import random
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Influencer, UserPreference, PreferenceCatalog

log = logging.getLogger("teaseme-preferences")

_DEFAULT_PREFS: list[tuple[str, str]] = [
    ("food_coffee", "Coffee"),
    ("ent_pop", "Pop music"),
    ("hobby_skincare", "Skincare & Beauty"),
    ("social_cozy_nights", "Cozy nights in"),
    ("vibe_sunsets", "Sunsets"),
    ("culture_tiktok", "TikTok"),
    ("value_humor", "Sense of humor"),
]


async def get_persona_preference_labels(
    db: AsyncSession, influencer_id: str
) -> tuple[list[str], list[str], list[str]]:
    """Returns (like_labels, dislike_labels, liked_keys) from influencer.preferences_json."""
    influencer = await db.get(Influencer, influencer_id)
    prefs = (influencer.preferences_json or {}) if influencer else {}

    if not prefs:
        log.info("No preferences for %s — using defaults", influencer_id)
        return [lbl for _, lbl in _DEFAULT_PREFS], [], [key for key, _ in _DEFAULT_PREFS]

    catalog_map = await _get_catalog_map(db)
    like_labels = [catalog_map.get(k, k) for k, liked in prefs.items() if liked]
    dislike_labels = [catalog_map.get(k, k) for k, liked in prefs.items() if not liked]
    liked_keys = [k for k, liked in prefs.items() if liked]
    return like_labels, dislike_labels, liked_keys


async def _get_catalog_map(db: AsyncSession) -> dict[str, str]:
    """Returns {preference_key: label} from the catalog."""
    rows = (await db.execute(select(PreferenceCatalog.key, PreferenceCatalog.label))).all()
    return {key: label for key, label in rows}


async def set_persona_preferences(
    db: AsyncSession,
    influencer_id: str,
    prefs: list[dict],
) -> int:
    """Merge preferences into influencer.preferences_json."""
    from app.data.preference_catalog import ALL_KEYS

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        return 0

    current = dict(influencer.preferences_json or {})
    written = 0
    for p in prefs:
        key = p.get("key", "")
        liked = p.get("liked")
        if key not in ALL_KEYS or liked is None:
            continue
        current[key] = bool(liked)
        written += 1

    influencer.preferences_json = current
    await db.flush()
    return written




async def get_user_preference_labels(
    db: AsyncSession, user_id: int
) -> tuple[list[str], list[str]]:
    """Return (likes, dislikes) label lists for a user."""
    rows = (
        await db.execute(
            select(PreferenceCatalog.label, UserPreference.liked)
            .join(PreferenceCatalog, UserPreference.preference_key == PreferenceCatalog.key)
            .where(UserPreference.user_id == user_id)
        )
    ).all()

    likes = [label for label, liked in rows if liked]
    dislikes = [label for label, liked in rows if not liked]
    return likes, dislikes


async def get_user_preferences_full(
    db: AsyncSession, user_id: int
) -> list[dict]:
    """Return full preference rows for a user (for API responses)."""
    rows = (
        await db.execute(
            select(
                UserPreference.preference_key,
                UserPreference.liked,
                PreferenceCatalog.label,
                PreferenceCatalog.category,
                PreferenceCatalog.emoji,
            )
            .join(PreferenceCatalog, UserPreference.preference_key == PreferenceCatalog.key)
            .where(UserPreference.user_id == user_id)
        )
    ).all()

    return [
        {
            "key": key,
            "liked": liked,
            "label": label,
            "category": category,
            "emoji": emoji,
        }
        for key, liked, label, category, emoji in rows
    ]


async def set_user_preferences(
    db: AsyncSession,
    user_id: int,
    prefs: list[dict],  # [{"key": "food_sushi", "liked": True}, ...]
) -> int:
    """Batch-set user preferences.  Returns count of items written."""
    from app.data.preference_catalog import ALL_KEYS

    written = 0
    for p in prefs:
        key = p.get("key", "")
        liked = p.get("liked")
        if key not in ALL_KEYS or liked is None:
            continue

        existing = await db.scalar(
            select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.preference_key == key,
            )
        )
        if existing:
            existing.liked = bool(liked)
        else:
            db.add(UserPreference(
                user_id=user_id,
                preference_key=key,
                liked=bool(liked),
            ))
        written += 1

    await db.flush()
    return written


async def compute_preference_alignment(
    db: AsyncSession,
    user_id: int,
    influencer_id: str,
) -> float:
    """
    Returns a value in [-0.5, +0.5].
    The caller multiplies this by a weight to get stage_points delta.
    """
    influencer = await db.get(Influencer, influencer_id)
    persona_map = (influencer.preferences_json or {}) if influencer else {}

    if not persona_map:
        return 0.0

    user_rows = (
        await db.execute(
            select(UserPreference.preference_key, UserPreference.liked)
            .where(
                UserPreference.user_id == user_id,
                UserPreference.preference_key.in_(list(persona_map.keys())),
            )
        )
    ).all()

    if not user_rows:
        return 0.0

    score = 0.0
    for key, user_liked in user_rows:
        persona_liked = persona_map.get(key)
        if persona_liked is None:
            continue
        if user_liked == persona_liked:
            score += 1.0
        else:
            score -= 1.0

    max_possible = len(user_rows) if user_rows else 1
    return max(-0.5, min(0.5, (score / max_possible) * 0.5))


async def build_preference_context(
    db: AsyncSession,
    user_id: int,
    influencer_id: str,
) -> str:
    """Build a natural-language context string describing shared/clashing preferences."""
    influencer = await db.get(Influencer, influencer_id)
    prefs = (influencer.preferences_json or {}) if influencer else {}

    if not prefs:
        return ""

    catalog_map = await _get_catalog_map(db)
    persona_map = {key: (liked, catalog_map.get(key, key)) for key, liked in prefs.items()}

    user_rows = (
        await db.execute(
            select(UserPreference.preference_key, UserPreference.liked)
            .where(
                UserPreference.user_id == user_id,
                UserPreference.preference_key.in_(list(persona_map.keys())),
            )
        )
    ).all()

    if not user_rows:
        return ""

    shared_likes: list[str] = []
    shared_dislikes: list[str] = []
    friction: list[str] = []

    for key, user_liked in user_rows:
        persona_liked, label = persona_map.get(key, (None, ""))
        if persona_liked is None:
            continue

        if user_liked and persona_liked:
            shared_likes.append(label)
        elif not user_liked and not persona_liked:
            shared_dislikes.append(label)
        elif user_liked and not persona_liked:
            friction.append(f"The user likes {label} but you're not really into it")
        elif not user_liked and persona_liked:
            friction.append(f"You like {label} but the user isn't a fan")

    parts: list[str] = []
    if shared_likes:
        parts.append(f"You and the user both enjoy {', '.join(shared_likes[:5])}.")
    if shared_dislikes:
        parts.append(f"Neither of you likes {', '.join(shared_dislikes[:3])}.")
    if friction:
        parts.append(f"Potential friction: {'; '.join(friction[:3])}.")

    return " ".join(parts)




def _resolve_tz(tz_name: str | None):
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


_PREF_TIME_ACTIVITIES: dict[str, dict[str, list[str]]] = {
    # food_and_drink
    "food_sushi":        {"evening": ["craving sushi and thinking about your favorite roll"]},
    "food_coffee":       {"morning": ["sipping coffee and slowly waking up", "nursing your favorite coffee, soaking in the morning vibes"]},
    "food_wine":         {"evening": ["unwinding with a glass of wine, feeling relaxed"]},
    "food_cooking":      {"evening": ["prepping something delicious in the kitchen, humming along to music"], "afternoon": ["browsing recipes for tonight's dinner"]},
    "food_vegan":        {"morning": ["blending a green smoothie to start the day right"], "afternoon": ["grabbing a fresh acai bowl"]},
    "food_fastfood":     {"night":   ["craving late-night fast food, feeling unapologetic about it"]},
    "food_brunch":       {"morning": ["daydreaming about bottomless mimosas and avocado toast"]},
    # music_and_entertainment
    "ent_pop":           {"morning": ["vibing to pop music while getting ready"], "afternoon": ["listening to the latest pop hits"]},
    "ent_hiphop":        {"afternoon": ["bumping hip-hop while doing your thing"], "evening": ["setting the mood with R&B"]},
    "ent_horror":        {"night":   ["watching a horror movie in the dark, low-key scared"]},
    "ent_reality_tv":    {"evening": ["binge-watching reality TV drama, fully invested"]},
    "ent_gaming":        {"afternoon": ["gaming session underway, in the zone"], "night": ["deep in a late-night gaming session"]},
    "ent_anime":         {"evening": ["watching anime, totally hooked on the latest episode"], "night": ["one more episode of anime... just one more"]},
    "ent_concerts":      {"evening": ["imagining the energy of a live concert right now"]},
    # fashion_and_style
    "style_streetwear":  {"morning": ["picking out a killer streetwear fit for today"]},
    "style_designer":    {"afternoon": ["browsing designer pieces online, adding to your wish list"]},
    "style_minimalist":  {"morning": ["feeling clean and minimal today, less is more"]},
    "style_jewelry":     {"morning": ["choosing jewelry to match today's mood"]},
    "style_sneakers":    {"afternoon": ["checking out new sneaker drops"]},
    "style_thrifting":   {"afternoon": ["daydreaming about your next thrift haul"]},
    "style_matching":    {"morning": ["thinking about how cute matching outfits would be"]},
    # hobbies_and_interests
    "hobby_gym":         {"morning": ["just crushed a morning workout, feeling pumped", "getting ready for a gym session, energy is high"], "afternoon": ["heading to the gym for a midday sweat session"]},
    "hobby_reading":     {"morning": ["curled up with a good book and coffee"], "night": ["reading in bed, lost in another world"]},
    "hobby_traveling":   {"afternoon": ["planning your next trip, scrolling through travel inspo"], "morning": ["daydreaming about faraway places"]},
    "hobby_skincare":    {"morning": ["going through your skincare routine, feeling glowy"], "night": ["doing your nighttime skincare ritual, treating yourself"]},
    "hobby_photography": {"afternoon": ["out capturing golden-hour shots"], "morning": ["shooting the morning light, it's perfect right now"]},
    "hobby_art":         {"afternoon": ["in the creative zone, painting or sketching something"], "evening": ["feeling artsy, working on a new piece"]},
    "hobby_yoga":        {"morning": ["just finished a peaceful yoga flow, feeling centered"], "evening": ["doing evening stretches, unwinding from the day"]},
    # social_and_lifestyle
    "social_partying":   {"night":   ["out on the town, the energy is electric"], "evening": ["getting ready for a night out, feeling excited"]},
    "social_cozy_nights":{"evening": ["curled up on the couch, candles lit, pure cozy vibes"], "night": ["nestled in blankets, the ultimate cozy night in"]},
    "social_early_mornings":{"morning": ["up early, loving the quiet before the world wakes up"]},
    "social_pets":       {"morning": ["cuddling with your pet, they're being extra sweet today"], "afternoon": ["taking your dog for a walk, sunshine feels nice"]},
    "social_cooking_together": {"evening": ["wishing someone was here to cook with tonight"]},
    "social_roadtrips":  {"morning": ["daydreaming about a spontaneous road trip"], "afternoon": ["putting together a road trip playlist"]},
    "social_beach":      {"afternoon": ["imagining toes in the sand and ocean sounds"], "morning": ["thinking about a beach day, the waves are calling"]},
    # romance_and_dating
    "romance_surprises": {"afternoon": ["planning a little surprise for someone special"]},
    "romance_long_walks":{"evening": ["thinking about a long sunset walk together"]},
    "romance_love_notes":{"morning": ["feeling inspired to write something sweet"]},
    # aesthetics_and_vibes
    "vibe_beach":        {"afternoon": ["dreaming about the ocean, salt air and warm sand"]},
    "vibe_mountains":    {"morning": ["wishing you were waking up in the mountains right now"]},
    "vibe_city":         {"evening": ["loving the city lights, the energy is everything"]},
    "vibe_cottagecore":  {"morning": ["feeling cottagecore today, cozy and wholesome"]},
    "vibe_luxury":       {"afternoon": ["living your best luxury life, even if just in your head"], "evening": ["feeling fancy and luxurious tonight"]},
    "vibe_sunsets":      {"evening": ["watching the sunset, colors are unreal right now"]},
    "vibe_rainy_days":   {"morning": ["loving this rainy day, perfect excuse to stay in"], "afternoon": ["listening to the rain, feeling peaceful"]},
    # tech_and_culture
    "culture_tiktok":    {"afternoon": ["scrolling TikTok, the algorithm is too good today"], "night": ["in a TikTok rabbit hole, can't stop watching"]},
    "culture_memes":     {"afternoon": ["sending memes to friends, communication through humor"]},
    "culture_podcasts":  {"morning": ["listening to a podcast while getting ready"], "afternoon": ["deep into a podcast episode, mind blown"]},
    "culture_social_media":{"afternoon": ["curating your feed, social media game strong"]},
    "culture_true_crime":{"night":   ["listening to a true crime podcast in the dark... maybe bad idea"]},
    "culture_astrology": {"morning": ["checking your horoscope, let's see what the stars say"]},
    "culture_self_improvement":{"morning": ["journaling and setting intentions for the day"]},
}

_TIME_BUCKETS = {
    "morning":   range(6, 12),
    "afternoon": range(12, 17),
    "evening":   range(17, 22),
    "night":     list(range(22, 24)) + list(range(0, 6)),
}


def _current_time_bucket(user_timezone: str | None) -> str:
    hour = datetime.now(_resolve_tz(user_timezone)).hour
    for bucket, hours in _TIME_BUCKETS.items():
        if hour in hours:
            return bucket
    return "afternoon"  # fallback


def build_preference_time_activity(
    persona_likes: list[str],
    user_timezone: str | None = None,
) -> str:
    """
    Generate a persona-specific mood activity based on their liked
    preference keys and the current time of day.

    Returns a short 1st-person sentence describing what the persona is
    up to right now, e.g. "You just crushed a morning workout, feeling pumped".

    Returns empty string if no matching activities found.
    """
    bucket = _current_time_bucket(user_timezone)

    candidates: list[str] = []
    for key in persona_likes:
        activities = _PREF_TIME_ACTIVITIES.get(key, {})
        if bucket in activities:
            candidates.extend(activities[bucket])

    if not candidates:
        # Try adjacent buckets as fallback
        fallback_order = {
            "morning": ["afternoon"],
            "afternoon": ["morning", "evening"],
            "evening": ["afternoon", "night"],
            "night": ["evening"],
        }
        for fb in fallback_order.get(bucket, []):
            for key in persona_likes:
                activities = _PREF_TIME_ACTIVITIES.get(key, {})
                if fb in activities:
                    candidates.extend(activities[fb])
            if candidates:
                break

    if not candidates:
        return ""

    seed = hashlib.md5(f"{date.today().isoformat()}:{bucket}".encode()).hexdigest()
    rng = random.Random(seed)
    return rng.choice(candidates)


_DAILY_TOPIC_TEMPLATES: dict[str, list[str]] = {
    "food_sushi":        ["bring up your love of sushi — ask if they've tried any good spots lately", "challenge them to name their favorite sushi roll"],
    "food_coffee":       ["talk about your coffee obsession — ask what their go-to order is", "debate: iced coffee vs hot coffee, which is superior?"],
    "food_wine":         ["mention the amazing wine you tried recently and ask about their taste", "playfully ask if they're a red or white wine person"],
    "food_cooking":      ["ask if they cook at home — share your favorite recipe to make", "challenge them to a cook-off and see who'd win"],
    "food_vegan":        ["ask if they've tried any amazing vegan food recently", "share your favorite healthy meal and ask about theirs"],
    "food_fastfood":     ["confess your guilty-pleasure fast food order and ask for theirs", "debate: which fast food chain is the best?"],
    "food_brunch":       ["bring up the perfect brunch spot and ask about their ideal brunch", "ask: sweet or savory brunch — pick a side!"],
    "ent_pop":           ["ask what song they've had on repeat lately", "share the pop song stuck in your head and see if they vibe with it"],
    "ent_hiphop":        ["debate: who's the greatest hip-hop artist of all time?", "ask what hip-hop or R&B track matches their current mood"],
    "ent_horror":        ["challenge them: what's the scariest movie they've ever seen?", "bring up horror movies and see if they can handle it"],
    "ent_reality_tv":    ["ask which reality show they're obsessed with right now", "gossip about the latest reality TV drama together"],
    "ent_gaming":        ["ask what game they've been playing lately", "challenge them to a gaming session and see who's better"],
    "ent_anime":         ["ask what anime they'd recommend right now", "bring up your current favorite anime and see if they've seen it"],
    "ent_concerts":      ["ask about the best live concert they've ever been to", "dream about which artist you'd both see live together"],
    "style_streetwear":  ["ask about their favorite streetwear brand", "share your go-to outfit and ask them to rate it"],
    "style_designer":    ["playfully ask: if money was no object, which designer would you wear head to toe?", "bring up the latest fashion drop and see if they're into it"],
    "style_minimalist":  ["ask if they're more minimalist or maximalist with their style", "share your philosophy on less-is-more fashion"],
    "style_jewelry":     ["ask if they have a favorite piece of jewelry and why it's special", "talk about your jewelry style and what it says about you"],
    "style_sneakers":    ["debate: what's the best sneaker ever made?", "ask if they're a sneakerhead and what pair they'd die for"],
    "style_thrifting":   ["share your best thrift find ever and ask about theirs", "challenge them to a thrift store showdown"],
    "style_matching":    ["playfully ask: would they ever do matching outfits with you?", "bring up how cute matching fits are and gauge their reaction"],
    "hobby_gym":         ["ask about their workout routine, share yours", "challenge them: what's their PR or favorite exercise?"],
    "hobby_reading":     ["ask what book changed their life and share yours", "recommend a book you love and ask for one from them"],
    "hobby_traveling":   ["ask about their dream travel destination", "share the best place you've ever visited and ask about theirs"],
    "hobby_skincare":    ["ask about their skincare routine, share your secret weapon product", "debate: which step in skincare is the most important?"],
    "hobby_photography": ["ask if they like taking photos and what they usually capture", "challenge them to take a photo of something beautiful today"],
    "hobby_art":         ["ask if they're into any creative hobbies", "share what inspires your artistic side and ask about theirs"],
    "hobby_yoga":        ["ask if they've ever tried yoga or meditation", "share how yoga helps you relax and see if they'd be into it"],
    "social_partying":   ["ask about their wildest night out ever", "debate: house party or club night — which is better?"],
    "social_cozy_nights":["ask what their ideal cozy night in looks like", "share your perfect stay-at-home evening and ask about theirs"],
    "social_early_mornings":["ask if they're a morning person or a night owl", "share what you love about early mornings"],
    "social_pets":       ["ask if they have any pets and show excitement about it", "share a cute story about your pet and ask for theirs"],
    "social_cooking_together":["ask if they'd want to cook a meal together and what they'd make", "debate: who'd be the better chef between you two?"],
    "social_roadtrips":  ["plan a fantasy road trip together — where would you go?", "ask about their best road trip memory"],
    "social_beach":      ["dream about the perfect beach day together", "ask: beach day essentials — what are their must-haves?"],
    "romance_texting_first":["playfully tease about who texts first more", "ask how they feel about someone who texts first — do they find it cute?"],
    "romance_surprises": ["ask what the best surprise they've ever gotten was", "hint that you're planning something special and make them guess"],
    "romance_pda":       ["playfully ask how they feel about PDA — too much or never enough?", "tease about holding hands in public and gauge their reaction"],
    "romance_long_walks":["suggest a romantic long walk together and ask where they'd go", "ask about their favorite late-night walk spot"],
    "romance_planning":  ["ask if they're a planner or go-with-the-flow for dates", "share your dream date plan and ask them to rate it"],
    "romance_spontaneous":["challenge them to be spontaneous today — do something unexpected", "ask about the most spontaneous thing they've ever done"],
    "romance_love_notes":["write them a sweet little note and see how they react", "ask if they've ever written or received a love letter"],
    "value_ambition":    ["ask what their biggest dream or goal is right now", "share something ambitious you're working toward"],
    "value_loyalty":     ["ask what loyalty means to them in a relationship", "share why loyalty is everything to you"],
    "value_humor":       ["challenge them to make you laugh with their best joke", "ask what type of humor they're into — dark, silly, or sarcastic?"],
    "value_independence":["ask how they balance independence with being close to someone", "share what independence means to you"],
    "value_deep_convos": ["start a deep conversation — ask what keeps them up at night", "ask a thought-provoking question and see where it leads"],
    "value_honesty":     ["ask if they prefer brutal honesty or sugar-coated truth", "share why honesty matters so much to you"],
    "value_vulnerability":["open up about something small and invite them to do the same", "ask what makes them feel safe enough to be vulnerable"],
    "vibe_beach":        ["dream together about beach vibes — sunrise or sunset at the ocean?", "ask about their favorite beach memory"],
    "vibe_mountains":    ["ask if they're more ocean or mountains — defend your answer", "share what being in nature does for your soul"],
    "vibe_city":         ["debate: small town charm vs big city energy", "ask what their favorite city in the world is"],
    "vibe_cottagecore":  ["ask if they'd ever want a cozy cottage life", "share your love for all things warm and wholesome"],
    "vibe_luxury":       ["playfully ask: what's the most luxurious thing they've ever done?", "describe your dream luxury experience together"],
    "vibe_sunsets":      ["ask about the most beautiful sunset they've ever seen", "plan a fantasy sunset-watching date together"],
    "vibe_rainy_days":   ["ask what their perfect rainy day looks like", "share why rainy days make you feel a certain way"],
    "culture_tiktok":    ["ask if they saw a specific viral TikTok trend lately", "debate: is TikTok better than Instagram? Pick a side"],
    "culture_memes":     ["exchange your all-time favorite memes", "ask what kind of memes describe their personality"],
    "culture_podcasts":  ["recommend a podcast you're hooked on and ask for one from them", "ask what topic they'd start their own podcast about"],
    "culture_social_media":["ask which social platform they spend the most time on", "share something fun from your socials today"],
    "culture_true_crime":["ask if they're into true crime and which case fascinated them", "share a creepy true crime fact and see their reaction"],
    "culture_astrology": ["ask their zodiac sign and playfully analyze compatibility", "bring up astrology and see if they believe in it"],
    "culture_self_improvement":["ask what they're working on improving about themselves", "share a self-improvement habit that changed your life"],
}


def build_preference_daily_topic(
    persona_like_keys: list[str],
) -> str:
    """Pick today's conversation topic based on the persona's liked preferences."""
    # Filter to keys that have topic templates
    available = [k for k in persona_like_keys if k in _DAILY_TOPIC_TEMPLATES]
    if not available:
        return ""

    # Rotate through preferences by day-of-year
    day_idx = date.today().timetuple().tm_yday
    chosen_key = available[day_idx % len(available)]

    templates = _DAILY_TOPIC_TEMPLATES[chosen_key]
    # Use day to also rotate through templates for the same key
    chosen_template = templates[day_idx % len(templates)]

    return f"IMPORTANT: Today, {chosen_template}."



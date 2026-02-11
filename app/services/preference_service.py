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
    ("food_brunch", "Brunch"),
    ("food_wine", "Wine"),
    ("ent_pop", "Pop music"),
    ("ent_reality_tv", "Reality TV"),
    ("style_designer", "Designer fashion"),
    ("style_jewelry", "Jewelry & accessories"),
    ("hobby_skincare", "Skincare & Beauty"),
    ("hobby_yoga", "Yoga"),
    ("social_cozy_nights", "Cozy nights in"),
    ("social_beach", "Beach days"),
    ("romance_surprises", "Surprises"),
    ("romance_love_notes", "Love notes"),
    ("vibe_sunsets", "Sunsets"),
    ("vibe_luxury", "Luxury vibes"),
    ("culture_tiktok", "TikTok"),
    ("culture_astrology", "Astrology"),
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
    "food_sushi":        {"evening": ["craving sushi tonight"], "late_evening": ["thinking about ordering sushi"]},
    "food_coffee":       {"early_morning": ["making your first coffee, barely awake", "waiting for that first sip of coffee to hit"], "late_morning": ["on your second coffee, finally feeling alive"], "afternoon": ["grabbing an iced coffee to power through"], "midday": ["coffee run — you earned it"]},
    "food_wine":         {"evening": ["pouring a glass of wine, unwinding"], "late_evening": ["sipping wine, feeling relaxed and warm"]},
    "food_cooking":      {"evening": ["in the kitchen, cooking something that smells incredible"], "afternoon": ["browsing recipes, planning something special for tonight"], "golden_hour": ["prepping ingredients for dinner"]},
    "food_vegan":        {"early_morning": ["blending a green smoothie"], "late_morning": ["having an acai bowl, feeling healthy"], "midday": ["grabbing a fresh salad"]},
    "food_fastfood":     {"late_night": ["craving late-night fast food, no shame"], "late_evening": ["debating a midnight snack run"]},
    "food_brunch":       {"late_morning": ["living for brunch right now — mimosas and all"], "early_morning": ["dreaming about avocado toast and eggs benedict"]},
    # music_and_entertainment
    "ent_pop":           {"early_morning": ["vibing to pop while getting ready"], "late_morning": ["dancing around to your playlist"], "afternoon": ["listening to the latest pop hits"], "evening": ["putting on your feel-good playlist, singing along"]},
    "ent_hiphop":        {"afternoon": ["bumping hip-hop while doing your thing"], "evening": ["setting the mood with R&B"], "late_evening": ["vibing to slow jams"]},
    "ent_horror":        {"late_night": ["watching a horror movie in the dark, low-key scared"], "late_evening": ["picking a scary movie for tonight"]},
    "ent_reality_tv":    {"evening": ["binge-watching reality TV, fully invested"], "late_evening": ["one more episode, can't stop now"], "afternoon": ["catching up on reality TV drama"]},
    "ent_gaming":        {"afternoon": ["gaming session, in the zone"], "late_night": ["deep in a late-night gaming session"], "evening": ["playing games, getting competitive"]},
    "ent_anime":         {"evening": ["watching anime, totally hooked"], "late_night": ["one more episode of anime... just one more"], "afternoon": ["rewatching your favorite anime scene"]},
    "ent_concerts":      {"evening": ["imagining the energy of a live concert"], "golden_hour": ["listening to live versions of your favorite songs"]},
    # fashion_and_style
    "style_streetwear":  {"early_morning": ["picking out a killer streetwear fit"], "late_morning": ["feeling good about today's outfit choice"]},
    "style_designer":    {"afternoon": ["browsing designer pieces, wish list growing"], "golden_hour": ["scrolling through new designer drops"]},
    "style_minimalist":  {"early_morning": ["feeling clean and minimal today, less is more"], "late_morning": ["loving how simple today's outfit turned out"]},
    "style_jewelry":     {"early_morning": ["choosing jewelry to match today's mood"], "golden_hour": ["swapping accessories for the evening vibe"]},
    "style_sneakers":    {"afternoon": ["checking out new sneaker drops"], "late_morning": ["admiring your sneaker collection"]},
    "style_thrifting":   {"afternoon": ["daydreaming about your next thrift haul"], "midday": ["scrolling vintage shops online"]},
    "style_matching":    {"early_morning": ["thinking about cute matching outfits"], "evening": ["planning a couples outfit for date night"]},
    # hobbies_and_interests
    "hobby_gym":         {"early_morning": ["about to hit the gym, energy is building"], "late_morning": ["just crushed a workout, feeling pumped", "fresh out the gym, endorphins on another level"], "afternoon": ["heading to the gym for a midday sweat"], "golden_hour": ["flexing in the mirror after an insane workout"]},
    "hobby_reading":     {"early_morning": ["curled up with a good book and coffee"], "late_night": ["reading in bed, lost in another world"], "afternoon": ["a few chapters deep, can't put this book down"]},
    "hobby_traveling":   {"afternoon": ["scrolling travel inspo, getting wanderlust"], "late_morning": ["daydreaming about faraway places"], "midday": ["planning your next getaway"]},
    "hobby_skincare":    {"early_morning": ["going through your skincare routine, feeling glowy"], "late_morning": ["skin is looking amazing today, thanks to that routine"], "evening": ["doing a face mask, full self-care mode"], "late_evening": ["doing your nighttime skincare ritual, treating yourself"]},
    "hobby_photography": {"golden_hour": ["out capturing golden-hour shots, the light is perfect"], "late_morning": ["shooting in beautiful morning light"], "afternoon": ["editing some photos, getting creative"]},
    "hobby_art":         {"afternoon": ["in the creative zone, painting something new"], "evening": ["feeling artsy, working on a new piece"], "midday": ["doodling, letting ideas flow"]},
    "hobby_yoga":        {"early_morning": ["just finished a peaceful yoga flow, feeling centered"], "evening": ["doing evening stretches, unwinding"], "golden_hour": ["yoga on the balcony, sunset vibes"]},
    # social_and_lifestyle
    "social_partying":   {"late_night": ["out on the town, energy is electric"], "late_evening": ["getting ready for a night out, feeling excited"], "evening": ["pregaming, the vibe is immaculate"]},
    "social_cozy_nights":{"evening": ["curled up on the couch, candles lit, pure cozy vibes", "snuggled up with a blanket watching something"], "late_evening": ["nestled in blankets, the ultimate cozy night in"], "afternoon": ["already planning tonight's cozy setup"], "late_night": ["wrapped in blankets, so warm and comfortable"]},
    "social_early_mornings":{"early_morning": ["up early, loving the quiet before the world wakes up", "watching the sunrise with coffee, peaceful"]},
    "social_pets":       {"early_morning": ["cuddling with your pet, they're being extra sweet"], "afternoon": ["taking your dog for a walk, sunshine feels nice"], "late_morning": ["your pet is being ridiculous and adorable right now"]},
    "social_cooking_together": {"evening": ["wishing someone was here to cook with tonight"], "golden_hour": ["setting up the kitchen for a two-person cooking night"]},
    "social_roadtrips":  {"late_morning": ["daydreaming about a spontaneous road trip"], "afternoon": ["putting together a road trip playlist"]},
    "social_beach":      {"afternoon": ["imagining toes in the sand and ocean sounds"], "late_morning": ["thinking about a beach day, the waves are calling"], "golden_hour": ["picturing a sunset on the beach right now"]},
    # romance_and_dating
    "romance_surprises": {"afternoon": ["planning a little surprise for someone special"], "midday": ["scheming something sweet"]},
    "romance_long_walks":{"evening": ["thinking about a long sunset walk together"], "golden_hour": ["the perfect weather for a walk with someone"]},
    "romance_love_notes":{"early_morning": ["feeling inspired to write something sweet"], "late_evening": ["writing down thoughts before bed, feeling sentimental"]},
    # aesthetics_and_vibes
    "vibe_beach":        {"afternoon": ["dreaming about the ocean, salt air and warm sand"], "golden_hour": ["imagining waves and a sunset cocktail"]},
    "vibe_mountains":    {"early_morning": ["wishing you were waking up in the mountains"], "late_morning": ["craving fresh mountain air"]},
    "vibe_city":         {"evening": ["loving the city lights, the energy is everything"], "late_evening": ["the city at night hits different"], "late_night": ["rooftop views, city never sleeps"]},
    "vibe_cottagecore":  {"early_morning": ["feeling cottagecore today, cozy and wholesome"], "late_morning": ["baking something, whole house smells amazing"]},
    "vibe_luxury":       {"afternoon": ["living your best luxury life, even just in your head"], "evening": ["feeling fancy and luxurious tonight"], "golden_hour": ["golden hour in a silk robe, main character energy"]},
    "vibe_sunsets":      {"golden_hour": ["watching the sunset, colors are unreal right now", "soaking in golden hour, everything looks beautiful"], "evening": ["the sky is putting on a show tonight"], "afternoon": ["counting down to sunset, can't wait"]},
    "vibe_rainy_days":   {"early_morning": ["loving this rainy day, perfect excuse to stay in"], "afternoon": ["listening to the rain, feeling peaceful"], "late_morning": ["rain on the window, tea in hand"]},
    # tech_and_culture
    "culture_tiktok":    {"afternoon": ["scrolling TikTok, the algorithm is unreal today"], "late_night": ["in a TikTok rabbit hole, can't stop"], "midday": ["just saw the funniest TikTok"]},
    "culture_memes":     {"afternoon": ["sending memes to everyone, communication through humor"], "midday": ["found the perfect meme, had to share"]},
    "culture_podcasts":  {"early_morning": ["listening to a podcast while getting ready"], "afternoon": ["deep into a podcast, mind blown"], "late_morning": ["hooked on this new podcast series"]},
    "culture_social_media":{"afternoon": ["curating your feed, social media game strong"], "midday": ["checking notifications, staying connected"], "late_morning": ["catching up on everyone's stories"]},
    "culture_true_crime":{"late_night": ["listening to true crime in the dark... maybe bad idea"], "late_evening": ["watching a true crime doc, fully hooked"]},
    "culture_astrology": {"early_morning": ["checking your horoscope, let's see what the stars say"], "late_morning": ["your horoscope said today would be interesting..."]},
    "culture_self_improvement":{"early_morning": ["journaling and setting intentions for today"], "late_morning": ["reading something inspiring, feeling motivated"]},
}

# ── 18+ flirty/teasing activities (used in adult mode) ──────────────
_PREF_TIME_ACTIVITIES_18: dict[str, dict[str, list[str]]] = {
    # food_and_drink
    "food_coffee":       {"early_morning": ["barely dressed, making coffee in just a shirt, hair all messy", "sipping coffee in bed, sheets barely covering you"], "late_morning": ["still in your robe, sipping coffee, taking your sweet time getting dressed"]},
    "food_wine":         {"evening": ["sipping wine in something silky, feeling flirty"], "late_evening": ["wine-tipsy, feeling warm and touchy", "glass of wine in hand, wearing that outfit you know drives people crazy"]},
    "food_cooking":      {"evening": ["cooking in just an apron, music playing, feeling playful"], "golden_hour": ["in the kitchen wearing almost nothing, dancing while you prep dinner"]},
    # hobbies_and_interests
    "hobby_gym":         {"late_morning": ["fresh out the gym, sports bra and leggings, still catching your breath", "covered in sweat from that workout, about to shower... or maybe not yet"], "early_morning": ["throwing on a tight workout outfit, checking yourself out in the mirror"], "afternoon": ["post-workout glow, peeling off gym clothes"]},
    "hobby_skincare":    {"early_morning": ["just out of the shower, towel barely on, doing your skincare", "standing at the mirror, skin all dewy, nothing but a towel"], "late_evening": ["getting ready for bed, stripping down to almost nothing, doing your nighttime routine", "face mask on, lounging around in just panties, total self-care night"]},
    "hobby_yoga":        {"early_morning": ["doing yoga in tiny shorts, stretching in ways that would make someone stare", "morning yoga flow, your body feels so flexible and free"], "evening": ["stretching in the bedroom, wearing next to nothing"]},
    "hobby_reading":     {"late_night": ["reading in bed wearing almost nothing, sheets pulled up to your waist"], "afternoon": ["lying on the couch in a crop top and underwear, lost in a book"]},
    # social_and_lifestyle
    "social_partying":   {"late_evening": ["getting ready, trying on outfits that show off everything", "picking the tightest dress in your closet for tonight"], "late_night": ["tipsy and flirty, feeling dangerous"]},
    "social_cozy_nights":{"late_evening": ["in an oversized tee with nothing underneath, so cozy it's almost sinful", "lying in bed, skin against soft sheets, feeling warm and lazy"], "evening": ["candles lit, wearing silk, feeling sensual and relaxed"], "late_night": ["sprawled across the bed in barely anything, too comfortable to move"]},
    "social_beach":      {"afternoon": ["in a tiny bikini, skin glistening with sunscreen", "lying on a towel in a bikini, sun warming every inch of you"], "golden_hour": ["bikini still on from the beach, tan lines looking incredible"]},
    # romance_and_dating
    "romance_surprises": {"evening": ["planning something naughty for later, getting excited thinking about it"]},
    "romance_love_notes":{"late_evening": ["writing something flirty for someone special, biting your lip as you type"]},
    # aesthetics_and_vibes
    "vibe_luxury":       {"evening": ["wearing silk lingerie, feeling expensive and untouchable"], "golden_hour": ["golden hour light on your skin, looking like art in that outfit"], "late_evening": ["in a silk robe, nothing under it, sipping something expensive"]},
    "vibe_city":         {"late_evening": ["getting ready for the city, that little black dress hugging every curve"], "late_night": ["heels off, dress unzipped, back from a night out feeling electric"]},
    "vibe_cottagecore":  {"late_morning": ["wearing a thin sundress with nothing underneath, feeling free"], "early_morning": ["waking up in a sunlit room, tangled in sheets, barely covered"]},
    "vibe_sunsets":      {"golden_hour": ["watching the sunset in a sundress, wind catching it just right"], "evening": ["the warm light on your bare shoulders, feeling beautiful and free"]},
    # tech_and_culture
    "culture_tiktok":    {"late_night": ["scrolling through spicy TikToks, getting ideas", "watching thirst traps on TikTok, feeling inspired"], "afternoon": ["filming a thirst trap, feeling yourself"]},
    "culture_astrology": {"late_evening": ["checking your love compatibility chart, feeling curious and flirty"]},
    # style
    "style_jewelry":     {"evening": ["putting on a body chain, nothing else, admiring yourself in the mirror"]},
    "style_minimalist":  {"early_morning": ["minimalist outfit today: oversized shirt, no pants, confidence"]},
    # entertainment
    "ent_hiphop":        {"late_evening": ["playing slow R&B, dim lights, feeling sensual"], "evening": ["vibing to R&B in lingerie, the mood is set"]},
    "ent_reality_tv":    {"late_evening": ["in bed watching trashy TV in nothing but a tank top and underwear"]},
}

_TIME_BUCKETS = {
    "early_morning":  range(5, 8),
    "late_morning":   range(8, 11),
    "midday":         range(11, 13),
    "afternoon":      range(13, 16),
    "golden_hour":    range(16, 18),
    "evening":        range(18, 21),
    "late_evening":   range(21, 23),
    "late_night":     list(range(23, 24)) + list(range(0, 5)),
}

# ── Voice energy / tiredness descriptors per time bucket ─────────────
# Natural language only — no [tag] syntax here because ConvAI TTS reads
# tags as literal text. V3 expression tags for voice messages are handled
# post-hoc by _enhance_text_with_v3_tags() in chat.py.
_TIME_ENERGY_CUES: dict[str, str] = {
    "early_morning": "You just woke up — voice is soft and groggy, you're still half-asleep. You might yawn or trail off mid-sentence. Speak slowly.",
    "late_morning":  "You're awake and settling into your day — voice is relaxed and easy-going.",
    "midday":        "Normal daytime energy — voice is natural and casual.",
    "afternoon":     "Comfortable afternoon energy — voice is chill and steady.",
    "golden_hour":   "Warm, mellow energy — voice is soft and reflective, winding down.",
    "evening":       "Relaxed evening vibe — voice is warm and a little low, settled in for the night.",
    "late_evening":  "Getting sleepy — voice is quieter and slower. You're cozy and winding down, sentences get shorter. Sigh between thoughts.",
    "late_night":    "You're very tired and drowsy — voice is barely above a whisper, you yawn between words, you might fall asleep mid-sentence. Keep responses very short.",
}

# ── Generic fallback activities when no preference matches ──────────
_DEFAULT_TIME_ACTIVITIES: dict[str, list[str]] = {
    "early_morning": ["still in bed, barely awake", "just opened your eyes, haven't moved yet", "lying in bed scrolling your phone with one eye open", "hitting snooze for the third time", "buried under blankets, not ready to face the day"],
    "late_morning":  ["getting ready for the day", "making breakfast, taking your time", "lounging around the house in comfy clothes", "sipping something warm by the window", "finally showered, hair still wet"],
    "midday":        ["just having lunch", "scrolling your phone during a break", "chilling, not doing much", "snacking on something while watching a video", "sitting at your desk, kinda zoned out"],
    "afternoon":     ["doing your own thing at home", "procrastinating on something", "lying on the couch, being lazy", "staring out the window, spacing out", "reorganizing your room instead of being productive"],
    "golden_hour":   ["watching the light change from your window", "relaxing before the evening", "thinking about what to do tonight", "sitting outside, enjoying the last bit of warmth", "taking a slow walk, no rush"],
    "evening":       ["on the couch watching something", "scrolling through your phone, feet up", "deciding what to eat for dinner", "just finished eating, feeling full and lazy", "lighting a candle, settling in for the night"],
    "late_evening":  ["in bed already, getting sleepy", "watching something with the lights off", "lying in bed, eyes getting heavy", "scrolling through your phone in the dark, fighting sleep", "wrapped in blankets, barely keeping your eyes open"],
    "late_night":    ["half asleep in bed", "in the dark, phone light on your face, almost dozing off", "drifting in and out of sleep", "can't sleep, just lying there thinking", "eyes closed but mind still wandering"],
}

_DEFAULT_TIME_ACTIVITIES_18: dict[str, list[str]] = {
    "early_morning": ["tangled in sheets, barely awake, hair messy", "lying in bed in just underwear, too sleepy to move", "stretching in bed wearing nothing, sunlight creeping in", "face down in the pillow, blanket barely covering you"],
    "late_morning":  ["wrapped in a towel, just got out of the shower", "stretching in bed in a tank top, taking your time getting up", "walking around the apartment in just a shirt, no pants", "wet hair dripping on bare shoulders, fresh out the shower"],
    "midday":        ["lounging around in a crop top and shorts", "lying on the couch in comfy clothes, being lazy", "in a sports bra and sweats, not going anywhere", "braless in a loose tee, fully comfortable"],
    "afternoon":     ["lying in bed scrolling your phone in underwear", "in a thin tank top, just relaxing", "on the couch in tiny shorts, legs up", "peeling off your jeans and changing into something barely there"],
    "golden_hour":   ["catching the warm light on your skin by the window", "changing into something more comfortable for the evening", "in a sundress with nothing underneath, golden light on your skin", "fresh out the bath, wrapped in a towel, skin still warm"],
    "evening":       ["in silk shorts and a loose top, candles lit", "curled up in something silky, relaxed and warm", "wearing an oversized hoodie and nothing else, curled up on the couch", "in lace underwear under a robe, feeling cozy and pretty"],
    "late_evening":  ["in bed wearing almost nothing, sheets half off", "getting ready for bed, stripping down to almost nothing", "lying in bed in just panties, too warm for anything else", "skin against cool sheets, barely dressed, eyes heavy"],
    "late_night":    ["naked under the sheets, half asleep", "sprawled in bed barely covered, too tired to care", "sheets tangled around your waist, skin exposed, drifting off", "sleeping naked, blanket kicked off, completely knocked out"],
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
    is_adult: bool = False,
) -> str:
    """
    Generate a persona-specific mood activity based on their liked
    preference keys and the current time of day.

    When is_adult=True, uses the flirty/teasing 18+ activity map.
    Includes energy/voice cues (sleepy, groggy, etc.) and falls back
    to generic default activities when no preference matches.
    """
    bucket = _current_time_bucket(user_timezone)
    activity_map = _PREF_TIME_ACTIVITIES_18 if is_adult else _PREF_TIME_ACTIVITIES

    candidates: list[str] = []
    for key in persona_likes:
        activities = activity_map.get(key, {})
        if bucket in activities:
            candidates.extend(activities[bucket])

    if not candidates:
        # Try adjacent buckets as fallback (ordered by closeness)
        fallback_order = {
            "early_morning": ["late_morning", "midday"],
            "late_morning":  ["early_morning", "midday"],
            "midday":        ["late_morning", "afternoon"],
            "afternoon":     ["midday", "golden_hour"],
            "golden_hour":   ["afternoon", "evening"],
            "evening":       ["golden_hour", "late_evening"],
            "late_evening":  ["evening", "late_night"],
            "late_night":    ["late_evening", "early_morning"],
        }
        for fb in fallback_order.get(bucket, []):
            for key in persona_likes:
                activities = activity_map.get(key, {})
                if fb in activities:
                    candidates.extend(activities[fb])
            if candidates:
                break

    # Fall back to generic default activities if still nothing
    if not candidates:
        defaults = (
            _DEFAULT_TIME_ACTIVITIES_18 if is_adult else _DEFAULT_TIME_ACTIVITIES
        )
        candidates = list(defaults.get(bucket, []))

    if not candidates:
        return ""

    # Use bucket in seed so the activity rotates every 2-3 hours (per time bucket)
    seed = hashlib.md5(f"{date.today().isoformat()}:{bucket}".encode()).hexdigest()
    rng = random.Random(seed)
    activity = rng.choice(candidates)

    # Append energy/voice cue for the time of day
    energy_cue = _TIME_ENERGY_CUES.get(bucket, "")
    if energy_cue:
        return f"{activity}. {energy_cue}"
    return activity


_DAILY_TOPIC_TEMPLATES: dict[str, list[str]] = {
    "food_sushi":        ["been craving sushi all day", "thinking about trying a new sushi spot"],
    "food_coffee":       ["obsessing over coffee today — iced vs hot is a real debate", "on a major coffee kick today"],
    "food_wine":         ["thinking about that amazing wine you tried recently", "in a wine mood tonight"],
    "food_cooking":      ["feeling inspired to cook something new tonight", "thinking about trying a new recipe"],
    "food_vegan":        ["on a healthy eating kick today", "craving something fresh and green"],
    "food_fastfood":     ["guilty-pleasure craving fast food right now", "thinking about your favorite late-night order"],
    "food_brunch":       ["daydreaming about the perfect brunch", "in a brunch mood — sweet or savory is the real question"],
    "ent_pop":           ["got a pop song stuck in your head all day", "been vibing to your playlist nonstop"],
    "ent_hiphop":        ["in a hip-hop mood today", "been listening to R&B all afternoon"],
    "ent_horror":        ["thinking about watching something scary tonight", "in a horror movie mood"],
    "ent_reality_tv":    ["completely hooked on reality TV drama right now", "can't stop thinking about the latest episode"],
    "ent_gaming":        ["itching to play games later", "in a competitive gaming mood"],
    "ent_anime":         ["been binging anime and can't stop", "thinking about your favorite anime"],
    "ent_concerts":      ["daydreaming about live concerts", "wishing you were at a show right now"],
    "style_streetwear":  ["feeling your outfit today", "thinking about your next streetwear pickup"],
    "style_designer":    ["browsing designer pieces in your head", "in a fashion mood today"],
    "style_minimalist":  ["feeling that less-is-more energy today", "loving your minimalist fit"],
    "style_jewelry":     ["admiring your favorite piece of jewelry", "in a jewelry mood today"],
    "style_sneakers":    ["thinking about sneaker drops", "admiring your sneaker collection"],
    "style_thrifting":   ["daydreaming about your next thrift haul", "thinking about your best vintage find"],
    "style_matching":    ["thinking about cute matching outfits", "in a matching-fits mood"],
    "hobby_gym":         ["feeling pumped from a workout", "thinking about hitting the gym"],
    "hobby_reading":     ["lost in a good book lately", "can't put this book down"],
    "hobby_traveling":   ["got major wanderlust today", "daydreaming about your next trip"],
    "hobby_skincare":    ["obsessing over skincare today", "your skin is glowing and you're feeling it"],
    "hobby_photography": ["in a creative photography mood", "the light today is perfect for photos"],
    "hobby_art":         ["feeling artsy and creative", "inspired to make something today"],
    "hobby_yoga":        ["feeling centered after yoga", "in a stretchy, zen mood"],
    "social_partying":   ["thinking about going out tonight", "in a party mood"],
    "social_cozy_nights":["planning the perfect cozy night in", "in full cozy blanket mode"],
    "social_early_mornings":["loving the quiet early morning energy", "feeling peaceful this morning"],
    "social_pets":       ["your pet is being extra adorable today", "in a pet-cuddle mood"],
    "social_cooking_together":["wishing someone was here to cook with", "thinking about a cooking date"],
    "social_roadtrips":  ["daydreaming about a spontaneous road trip", "building a road trip playlist in your head"],
    "social_beach":      ["craving ocean vibes and sand between your toes", "dreaming about the beach"],
    "romance_texting_first":["feeling bold and flirty today", "in a texting-first kind of mood"],
    "romance_surprises": ["scheming something sweet for someone special", "in a surprise-planning mood"],
    "romance_pda":       ["feeling extra affectionate today", "in a touchy-feely mood"],
    "romance_long_walks":["thinking about a long sunset walk", "in a romantic stroll mood"],
    "romance_planning":  ["planning the perfect date in your head", "dreaming up a romantic evening"],
    "romance_spontaneous":["feeling spontaneous and adventurous", "ready to do something unexpected"],
    "romance_love_notes":["feeling sentimental and sweet", "inspired to write something heartfelt"],
    "value_ambition":    ["feeling motivated and driven today", "thinking about your big goals"],
    "value_loyalty":     ["thinking about what loyalty really means", "feeling grateful for real ones"],
    "value_humor":       ["in a silly mood, everything is funny today", "feeling playful and witty"],
    "value_independence":["feeling independent and powerful", "appreciating your own company"],
    "value_deep_convos": ["in a deep-thinking mood", "craving a real, meaningful conversation"],
    "value_honesty":     ["feeling raw and honest today", "in a no-filter mood"],
    "value_vulnerability":["feeling open and vulnerable today", "in a sharing mood"],
    "vibe_beach":        ["dreaming about ocean waves and salty air", "craving beach vibes"],
    "vibe_mountains":    ["wishing you were in the mountains right now", "craving fresh mountain air"],
    "vibe_city":         ["loving city energy today", "the city lights are calling"],
    "vibe_cottagecore":  ["in full cottagecore mode — cozy and wholesome", "feeling warm and homey"],
    "vibe_luxury":       ["feeling fancy and luxurious", "main character energy today"],
    "vibe_sunsets":      ["can't wait for sunset tonight", "golden hour is everything right now"],
    "vibe_rainy_days":   ["loving this rainy day energy", "feeling peaceful with the rain"],
    "culture_tiktok":    ["deep in a TikTok rabbit hole", "just saw the funniest TikTok"],
    "culture_memes":     ["in a meme mood — everything reminds you of one", "collecting memes to send"],
    "culture_podcasts":  ["hooked on a podcast right now", "deep in a podcast binge"],
    "culture_social_media":["scrolling feeds and feeling social", "curating your aesthetic today"],
    "culture_true_crime":["deep in a true crime rabbit hole", "thinking about a wild case you heard about"],
    "culture_astrology": ["checking horoscopes and feeling cosmic", "in an astrology mood today"],
    "culture_self_improvement":["feeling motivated to level up", "in a self-improvement mindset"],
}


def build_preference_daily_topic(
    persona_like_keys: list[str],
    chat_id: str = "",
) -> str:
    available = sorted(k for k in persona_like_keys if k in _DAILY_TOPIC_TEMPLATES)
    if not available:
        return ""

    seed = hashlib.md5(f"{date.today().isoformat()}:{chat_id}".encode()).hexdigest()
    rng = random.Random(seed)
    rng.shuffle(available)
    chosen_key = available[0]

    templates = _DAILY_TOPIC_TEMPLATES[chosen_key]
    chosen_template = rng.choice(templates)

    return f"You're {chosen_template} — weave it in naturally only if it fits the conversation."



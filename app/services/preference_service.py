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
    Returns empty string if no matching activities found.
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

    if not candidates:
        return ""

    # Use hour in seed so the activity rotates hourly
    hour = datetime.now(_resolve_tz(user_timezone)).hour
    seed = hashlib.md5(f"{date.today().isoformat()}:{hour}".encode()).hexdigest()
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
    available = sorted(k for k in persona_like_keys if k in _DAILY_TOPIC_TEMPLATES)
    if not available:
        return ""

    today = date.today()
    day_seed = today.isoformat()

    rng = random.Random(hashlib.md5(day_seed.encode()).hexdigest())
    rng.shuffle(available)
    chosen_key = available[0]

    templates = _DAILY_TOPIC_TEMPLATES[chosen_key]
    chosen_template = rng.choice(templates)

    return f"Today, {chosen_template}."



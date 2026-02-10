"""Brave Search Service — live trending context from news, cached in Redis."""

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.utils.redis_pool import get_redis

log = logging.getLogger("teaseme-brave-search")

_BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
_CACHE_TTL = 6 * 3600  # 6 hours
_TIMEOUT = 3.0  # seconds
_MAX_RESULTS_PER_QUERY = 2  # fetch a couple, pick the best 1


def _resolve_time_context(user_timezone: str | None = None) -> tuple[str, bool]:
    """Returns (time_bucket, is_weekend) for the user's local time."""
    try:
        tz = ZoneInfo(user_timezone) if user_timezone else timezone.utc
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    hour = now.hour
    is_weekend = now.weekday() >= 5  # Sat=5, Sun=6

    if 6 <= hour < 12:
        bucket = "morning"
    elif 12 <= hour < 17:
        bucket = "afternoon"
    elif 17 <= hour < 22:
        bucket = "evening"
    else:
        bucket = "night"

    return bucket, is_weekend


_PREF_TIME_QUERIES: dict[str, dict[str, list[str]]] = {
    "food_sushi": {
        "any":       ["sushi food trends news today"],
        "evening":   ["best sushi restaurants opening tonight"],
        "weekend":   ["sushi omakase trending"],
    },
    "food_coffee": {
        "morning":   ["morning coffee trends today", "best coffee news"],
        "afternoon": ["afternoon coffee culture news"],
        "any":       ["coffee trends today"],
    },
    "food_wine": {
        "evening":   ["wine tasting events tonight", "new wine releases"],
        "weekend":   ["wine bar events this weekend"],
        "any":       ["wine culture news today"],
    },
    "food_cooking": {
        "morning":   ["easy breakfast recipe trends"],
        "evening":   ["dinner recipe trends tonight"],
        "weekend":   ["weekend cooking trends brunch recipes"],
        "any":       ["cooking trends recipes trending"],
    },
    "food_vegan": {
        "any":       ["vegan food news trending"],
        "weekend":   ["vegan restaurants trending this weekend"],
    },
    "food_fastfood": {
        "any":       ["fast food news today new menu items"],
        "night":     ["late night fast food deals trending"],
    },
    "food_brunch": {
        "morning":   ["brunch spots trending today"],
        "weekend":   ["best weekend brunch trending"],
        "any":       ["brunch food trends"],
    },
    "ent_pop": {
        "any":       ["pop music news today", "new music releases today"],
        "morning":   ["new music drops today morning"],
        "weekend":   ["weekend music events concerts"],
    },
    "ent_hiphop": {
        "any":       ["hip hop music news today", "rap news today"],
        "night":     ["hip hop club events tonight"],
        "weekend":   ["rap concerts this weekend"],
    },
    "ent_horror": {
        "night":     ["horror movies streaming tonight", "scary movies trending"],
        "evening":   ["new horror film releases"],
        "weekend":   ["horror movies to watch this weekend"],
        "any":       ["horror movies news"],
    },
    "ent_reality_tv": {
        "evening":   ["reality TV tonight new episodes"],
        "any":       ["reality TV show news today"],
        "weekend":   ["reality TV marathon trending"],
    },
    "ent_gaming": {
        "night":     ["gaming streams live tonight", "gaming news tonight"],
        "evening":   ["new video game releases today"],
        "weekend":   ["gaming tournament this weekend"],
        "any":       ["gaming news today"],
    },
    "ent_anime": {
        "night":     ["anime episodes streaming tonight"],
        "weekend":   ["anime binge recommendations this weekend"],
        "any":       ["anime news today", "new anime releases"],
    },
    "ent_concerts": {
        "evening":   ["concerts tonight live music"],
        "weekend":   ["music festival this weekend", "concerts this weekend"],
        "any":       ["live concerts tours news"],
    },
    "style_streetwear": {
        "any":       ["streetwear fashion news drops"],
        "morning":   ["new streetwear drops today"],
        "weekend":   ["streetwear pop-up events this weekend"],
    },
    "style_designer": {
        "any":       ["designer fashion news luxury"],
        "weekend":   ["fashion shows events this weekend"],
    },
    "style_sneakers": {
        "morning":   ["sneaker releases dropping today"],
        "any":       ["sneaker releases news today"],
        "weekend":   ["sneaker events this weekend"],
    },
    "hobby_gym": {
        "morning":   ["morning workout fitness tips today"],
        "weekday":   ["weekday workout routine trending"],
        "afternoon": ["afternoon gym fitness trends"],
        "weekend":   ["weekend fitness events outdoor workout"],
        "any":       ["fitness trends today"],
    },
    "hobby_traveling": {
        "any":       ["travel news destinations trending"],
        "weekend":   ["weekend getaway deals trending", "travel destinations this weekend"],
        "weekday":   ["travel deals flight sales today"],
    },
    "hobby_skincare": {
        "morning":   ["morning skincare routine trends today"],
        "evening":   ["evening skincare routine trending"],
        "any":       ["skincare beauty trends today"],
    },
    "hobby_photography": {
        "morning":   ["golden hour photography tips morning"],
        "afternoon": ["photography trends today outdoor"],
        "evening":   ["sunset photography trending"],
        "any":       ["photography news trends"],
    },
    "hobby_art": {
        "any":       ["art news exhibitions today"],
        "weekend":   ["art exhibitions galleries open this weekend"],
    },
    "hobby_yoga": {
        "morning":   ["morning yoga meditation trending"],
        "evening":   ["evening relaxation wellness tips"],
        "any":       ["wellness yoga meditation trends"],
    },
    "social_partying": {
        "night":     ["nightlife events clubs tonight trending"],
        "evening":   ["party events tonight trending"],
        "weekend":   ["best parties this weekend nightlife events"],
        "any":       ["nightlife events trending"],
    },
    "social_pets": {
        "any":       ["pet news cute animals trending"],
        "weekend":   ["pet adoption events this weekend"],
    },
    "social_beach": {
        "morning":   ["beach weather today surf conditions"],
        "afternoon": ["beach activities today trending"],
        "weekend":   ["beach events this weekend"],
        "any":       ["beach travel destinations trending"],
    },
    "vibe_city": {
        "evening":   ["city events tonight urban"],
        "weekend":   ["city events this weekend things to do"],
        "any":       ["city life urban news trending"],
    },
    "vibe_luxury": {
        "any":       ["luxury lifestyle trending news"],
        "weekend":   ["luxury experiences events this weekend"],
    },
    "culture_tiktok": {
        "any":       ["TikTok viral trends today"],
        "morning":   ["TikTok trending this morning viral"],
    },
    "culture_memes": {
        "any":       ["viral memes trending today"],
    },
    "culture_podcasts": {
        "morning":   ["best podcasts today morning commute"],
        "weekday":   ["podcasts trending today commute"],
        "any":       ["popular podcasts trending today"],
    },
    "culture_social_media": {
        "any":       ["social media news trending"],
    },
    "culture_true_crime": {
        "night":     ["true crime stories tonight"],
        "evening":   ["true crime podcast episodes new"],
        "any":       ["true crime news cases today"],
    },
    "culture_astrology": {
        "morning":   ["horoscope today morning astrology"],
        "any":       ["astrology horoscope today"],
    },
    "culture_self_improvement": {
        "morning":   ["morning motivation self improvement tips"],
        "any":       ["self improvement trending"],
    },
}


def _build_search_queries(
    persona_like_keys: list[str],
    time_bucket: str,
    is_weekend: bool,
    max_queries: int = 2,
) -> list[str]:
    """Pick search queries relevant to the persona's liked preferences."""
    available: list[str] = []
    day_key = "weekend" if is_weekend else "weekday"

    for key in persona_like_keys:
        time_map = _PREF_TIME_QUERIES.get(key)
        if not time_map:
            continue

        if time_bucket in time_map:
            available.extend(time_map[time_bucket])
        elif day_key in time_map:
            available.extend(time_map[day_key])
        elif "any" in time_map:
            available.extend(time_map["any"])

    if not available:
        available = ["trending news today", "pop culture news today"]

    day_idx = date.today().timetuple().tm_yday
    selected: list[str] = []
    for i in range(min(max_queries, len(available))):
        idx = (day_idx + i) % len(available)
        q = available[idx]
        if q not in selected:
            selected.append(q)

    return selected


async def _search_brave_news(query: str) -> list[dict]:
    """Call Brave News Search API. Returns list of {title, description} dicts."""
    api_key = settings.BRAVE_SEARCH_API_KEY
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _BRAVE_NEWS_URL,
                params={
                    "q": query,
                    "count": _MAX_RESULTS_PER_QUERY,
                    "freshness": "pd",  # past 24 hours
                    "text_decorations": False,
                },
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )

            if resp.status_code != 200:
                log.warning("brave_search.api_error status=%s q=%r", resp.status_code, query)
                return []

            data = resp.json()
            results = data.get("results", [])

            return [
                {
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                }
                for r in results[:_MAX_RESULTS_PER_QUERY]
                if r.get("title")
            ]

    except httpx.TimeoutException:
        log.warning("brave_search.timeout q=%r", query)
        return []
    except Exception as exc:
        log.warning("brave_search.error q=%r err=%s", query, exc)
        return []


def _format_context(all_results: list[dict], query_keywords: list[str] | None = None) -> str:
    """Condense search results into a single casual context nugget."""
    if not all_results:
        return ""

    seen_titles: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        title_lower = r["title"].lower()
        if title_lower not in seen_titles:
            seen_titles.add(title_lower)
            unique.append(r)

    if not unique:
        return ""

    if query_keywords:
        stop = {"today", "latest", "new", "best", "top", "this", "the", "and", "for", "morning", "afternoon", "evening", "night", "weekend"}
        keywords = set()
        for kw in query_keywords:
            keywords.update(w for w in kw.lower().split() if w not in stop)

        def _score(r: dict) -> int:
            text = f"{r.get('title', '')} {r.get('description', '')}".lower()
            return sum(1 for k in keywords if k in text)

        unique.sort(key=_score, reverse=True)

    best = None
    for r in unique:
        desc = r.get("description", "").strip()
        if desc and len(desc) > 30:
            best = r
            break
    if not best:
        best = unique[0]

    title = best["title"].strip()
    desc = best.get("description", "").strip()
    if len(desc) > 100:
        desc = desc[:97] + "..."

    nugget = f"{title}: {desc}" if desc else title

    return (
        f"(You recently scrolled past something on your phone: \"{nugget}\". "
        f"You don't know all the details — you just saw the headline. "
        f"You might casually bring it up IF it fits the conversation naturally, "
        f"like \"omg did you see that thing about...\" but do NOT sound like a "
        f"news reporter. You're allowed to have a vague, half-remembered take on it. "
        f"If it doesn't fit the vibe, just ignore it entirely.)"
    )


async def fetch_trending_context(
    persona_like_keys: list[str],
    influencer_id: str,
    user_timezone: str | None = None,
) -> str:
    """Main entry point — returns a formatted live context string for the persona."""
    if not settings.BRAVE_SEARCH_API_KEY:
        return ""

    time_bucket, is_weekend = _resolve_time_context(user_timezone)
    day_type = "weekend" if is_weekend else "weekday"

    cache_key = f"brave_ctx:{influencer_id}:{date.today().isoformat()}:{time_bucket}:{day_type}"

    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            log.debug("brave_search.cache_hit key=%s", cache_key)
            return cached
    except Exception as exc:
        log.warning("brave_search.cache_read_error err=%s", exc)

    queries = _build_search_queries(persona_like_keys, time_bucket, is_weekend)
    log.info(
        "brave_search.fetching influencer=%s bucket=%s day=%s queries=%s",
        influencer_id, time_bucket, day_type, queries,
    )

    all_results: list[dict] = []
    for query in queries:
        results = await _search_brave_news(query)
        all_results.extend(results)

    context = _format_context(all_results, query_keywords=queries)

    try:
        redis = await get_redis()
        await redis.set(cache_key, context, ex=_CACHE_TTL)
        log.debug("brave_search.cached key=%s len=%d", cache_key, len(context))
    except Exception as exc:
        log.warning("brave_search.cache_write_error err=%s", exc)

    return context

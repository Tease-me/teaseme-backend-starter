from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bs4 import BeautifulSoup
from typing import Optional
import httpx
import re
import json

from app.db.session import get_db
from app.db.models import PreInfluencer
from app.core.config import settings

router = APIRouter(prefix="/social", tags=["social"])

class SocialValidateIn(BaseModel):
    platform: str
    handle: str


class SocialValidateOut(BaseModel):
    platform: str
    username: str
    followers_count: int


@router.post("/validate", response_model=SocialValidateOut)
async def validate_social_media(
    payload: SocialValidateIn,
    db: AsyncSession = Depends(get_db),
):
    platform = payload.platform.lower().strip()
    handle = payload.handle.strip()

    if platform != "instagram":
        raise HTTPException(400, "Only instagram supported for now.")

    # normaliza handle
    username = handle.lstrip("@").strip()
    normalized = username
    with_at = "@" + username

    result = await db.execute(
        select(PreInfluencer).where(
            (PreInfluencer.username == normalized) | (PreInfluencer.username == with_at)
        )
    )
    pre_inf = result.scalar_one_or_none()

    if not pre_inf:
        raise HTTPException(404, "Pre-influencer not found.")

    if not pre_inf.ig_user_id or not pre_inf.ig_access_token:
        raise HTTPException(400, "Instagram not connected.")

    url = f"https://graph.facebook.com/v19.0/{pre_inf.ig_user_id}"
    params = {
        "fields": "username,followers_count",
        "access_token": pre_inf.ig_access_token,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    print("IG USER RESPONSE:", data)

    if "error" in data:
        raise HTTPException(400, f"Instagram API error: {data['error']}")

    followers = data.get("followers_count", 0)
    ig_username = data.get("username", username)

    return SocialValidateOut(
        platform="instagram",
        username=ig_username,
        followers_count=followers,
    )


class FollowerResponse(BaseModel):
    count: int
    service: str
    username: str
    success: bool

@router.get("/")
async def root():
    return {"message": "Social Media Followers API"}

@router.get("/api/followers")
async def get_followers(
    service: str = Query(..., description="Social media service name"),
    username: str = Query(..., description="Username to get followers for")
):
    """
    Get follower count for a given social media service and username
    """
    try:
        count = await fetch_followers(service.lower(), username)
        return {
            "count": count,
            "service": service,
            "username": username,
            "success": True
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Internal server error: {str(e)}"})

async def get_twitter_followers_api(username: str, bearer_token: Optional[str] = None) -> int:
    """
    Get Twitter follower count using Twitter API v2
    Requires: Bearer token from Twitter Developer Portal
    """
    bearer_token = settings.TWITTER_BEARER_TOKEN

    if not bearer_token:
        raise ValueError("Twitter bearer token not provided")
    
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    headers = {
        'Authorization': f'Bearer {bearer_token}'
    }
    params = {
        'user.fields': 'public_metrics'
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and 'public_metrics' in data['data']:
            return int(data['data']['public_metrics']['followers_count'])
        else:
            raise ValueError("User not found")
        
async def fetch_followers(service: str, username: str) -> int:
    """
    Fetch follower count based on service type
    """
    if service == "instagram":
        return await get_instagram_followers(username)
    elif service == "twitter":
        # Try official API first if token is available
        import os
        from dotenv import load_dotenv
        load_dotenv()
        bearer_token = settings.TWITTER_BEARER_TOKEN
        if bearer_token:
            try:
                return await get_twitter_followers_api(username, bearer_token)
            except:
                # Fall back to scraping if API fails
                pass
        return await get_twitter_followers(username)
    elif service == "tiktok":
        return await get_tiktok_followers(username)
    elif service == "telegram":
        return await get_telegram_followers(username)

    else:
        raise ValueError(f"Unsupported service: {service}")

async def get_instagram_followers(username: str) -> int:
    """
    Get Instagram follower count using curl_cffi to bypass TLS fingerprinting.
    
    Uses Instagram's internal API with Chrome TLS impersonation to avoid
    being detected as a bot. Implements exponential backoff on rate limits.
    
    For production with high volume, use Instagram Graph API with OAuth tokens.
    """
    import asyncio
    import random
    import logging
    from curl_cffi import requests as curl_requests
    
    log = logging.getLogger(__name__)
    
    # Instagram's internal API endpoint (more reliable than web scraping)
    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    
    # Required headers - x-ig-app-id is critical for API access
    headers = {
        'x-ig-app-id': '936619743392459',  # Instagram Web App ID
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://www.instagram.com',
        'Referer': f'https://www.instagram.com/{username}/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }
    
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Add random delay to appear more human-like (2-5 seconds with variance)
            if attempt > 0:
                await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # Use curl_cffi with Chrome impersonation to bypass TLS fingerprinting
            # This runs in a thread since curl_cffi is synchronous
            def fetch_with_curl():
                return curl_requests.get(
                    api_url,
                    headers=headers,
                    impersonate="chrome120",  # Bypass TLS fingerprinting
                    timeout=15.0,
                )
            
            response = await asyncio.to_thread(fetch_with_curl)
            
            if response.status_code == 429:
                # Rate limited - exponential backoff: 2s, 4s, 8s
                wait_time = 2 ** (attempt + 1)
                log.warning(f"Instagram rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(wait_time)
                continue
            
            if response.status_code == 404:
                raise ValueError(f"Instagram user @{username} not found")
            
            if response.status_code == 401 or response.status_code == 403:
                log.warning(f"Instagram API returned {response.status_code} - may need proxy rotation")
                if attempt < max_retries - 1:
                    await asyncio.sleep(random.uniform(3.0, 6.0))
                    continue
                raise ValueError(
                    f"Instagram blocked the request (HTTP {response.status_code}). "
                    "Consider using residential proxies or Instagram Graph API with OAuth."
                )
            
            if response.status_code == 200:
                data = response.json()
                user_data = data.get('data', {}).get('user', {})
                
                if not user_data:
                    raise ValueError(f"No user data returned for @{username}")
                
                edge_followed_by = user_data.get('edge_followed_by', {})
                count = edge_followed_by.get('count', 0)
                
                if count >= 0:
                    log.info(f"Successfully fetched follower count for @{username}: {count}")
                    return count
            
            # Unexpected status code
            log.error(f"Instagram API returned unexpected status {response.status_code}")
            
        except ValueError:
            raise
        except Exception as e:
            log.error(f"Instagram fetch attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise Exception(f"Failed to fetch Instagram data after {max_retries} attempts: {str(e)}")
            continue
    
    raise ValueError(
        f"Could not extract follower count for @{username}. "
        "Instagram requires official API access for reliable data. "
        "Please use Instagram Graph API with OAuth for production."
    )

async def get_twitter_followers(username: str) -> int:
    """
    Get Twitter/X follower count
    Note: Twitter/X heavily restricts scraping. For production, use Twitter API v2.
    This function tries multiple methods to extract follower count.
    """
    try:
        url = f"https://twitter.com/{username}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Method 1: Look for JSON-LD structured data
            json_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        # Look for interactionStatistic
                        if 'interactionStatistic' in data:
                            for stat in data.get('interactionStatistic', []):
                                if 'interactionType' in stat and 'userInteractionCount' in stat:
                                    interaction_type = stat.get('interactionType', {}).get('@type', '')
                                    if 'FollowAction' in interaction_type or 'followers' in str(stat).lower():
                                        count = int(stat.get('userInteractionCount', 0))
                                        if count > 0:
                                            return count
                except:
                    continue
            
            # Method 2: Look for Twitter's API data in script tags
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and ('User' in script.string or 'followers_count' in script.string):
                    try:
                        # Try to find JSON data with user info
                        json_match = re.search(r'"followers_count":\s*(\d+)', script.string)
                        if json_match:
                            count = int(json_match.group(1))
                            if count > 0:
                                return count
                        
                        # Try to find in window.__INITIAL_STATE__ or similar
                        state_match = re.search(r'__INITIAL_STATE__\s*=\s*({.+?});', script.string, re.DOTALL)
                        if state_match:
                            data = json.loads(state_match.group(1))
                            # Navigate through the data structure
                            entities = data.get('entities', {})
                            users = entities.get('users', {})
                            for user_id, user_data in users.items():
                                if isinstance(user_data, dict) and 'screen_name' in user_data:
                                    if user_data.get('screen_name', '').lower() == username.lower():
                                        count = user_data.get('followers_count', 0)
                                        if count > 0:
                                            return count
                    except:
                        continue
            
            # Method 3: Look for meta tags
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                property_attr = meta.get('property', '')
                name_attr = meta.get('name', '')
                content = meta.get('content', '')
                
                if 'followers' in property_attr.lower() or 'followers' in name_attr.lower():
                    numbers = re.findall(r'([\d,]+)', content)
                    if numbers:
                        return int(numbers[0].replace(',', ''))
            
            # Method 4: Search in page text for follower patterns
            page_text = soup.get_text()
            # Look for patterns like "1,234 Followers" or "1.2M Followers"
            patterns = [
                r'([\d,]+)\s+[Ff]ollowers?',
                r'([\d.]+[KMB]?)\s+[Ff]ollowers?',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, page_text)
                if matches:
                    count_str = str(matches[0]).replace(',', '').upper()
                    # Handle K, M, B suffixes
                    if 'K' in count_str:
                        return int(float(count_str.replace('K', '')) * 1000)
                    elif 'M' in count_str:
                        return int(float(count_str.replace('M', '')) * 1000000)
                    elif 'B' in count_str:
                        return int(float(count_str.replace('B', '')) * 1000000000)
                    else:
                        return int(count_str)
            
            # Method 5: Try to extract from raw HTML (Twitter embeds data in various formats)
            try:
                # Look for patterns in the raw HTML
                patterns = [
                    r'"followers_count":\s*(\d+)',
                    r'"follower_count":\s*(\d+)',
                    r'followers["\']?\s*:\s*["\']?(\d+)',
                    r'Followers["\']?\s*:\s*["\']?(\d+)',
                    r'data-followers=["\']?(\d+)',
                ]
                all_matches = []
                for pattern in patterns:
                    matches = re.findall(pattern, html, re.I)
                    all_matches.extend([int(m) for m in matches if m.isdigit()])
                
                if all_matches:
                    # Filter reasonable follower counts (between 1 and 1 billion)
                    valid_counts = [m for m in all_matches if 1 <= m <= 1000000000]
                    if valid_counts:
                        # Return the most common or largest reasonable number
                        from collections import Counter
                        counter = Counter(valid_counts)
                        most_common = counter.most_common(1)[0][0]
                        return most_common
            except:
                pass
            
            # Method 6: Try using a third-party API or fallback
            # Note: Twitter/X is very restrictive, so scraping often fails
            # For production, you MUST use Twitter API v2 with Bearer token
            
            # If nothing found, raise an informative error
            raise ValueError(
                f"Could not extract follower count for @{username}. "
                "Twitter/X heavily restricts web scraping. "
                "For reliable data, please configure TWITTER_BEARER_TOKEN in backend/.env file. "
                "Get your Bearer Token from: https://developer.twitter.com/en/portal/dashboard"
            )
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to fetch Twitter data: {str(e)}")

async def get_tiktok_followers(username: str) -> int:
    """
    Get TikTok follower count
    Note: TikTok requires official API access
    For production, use TikTok API
    """
    try:
        url = f"https://www.tiktok.com/@{username}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # TikTok embeds data in script tags
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'follower' in script.string.lower():
                    numbers = re.findall(r'[\d,]+', script.string)
                    if numbers:
                        return int(numbers[0].replace(',', ''))
            
            return 0
    except Exception as e:
        raise Exception(f"Failed to fetch TikTok data: {str(e)}")

async def get_telegram_followers(username: str) -> int:
    """
    Get Telegram channel/group member count
    Note: Telegram Bot API can be used for this
    """
    try:
        url = f"https://t.me/{username}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for member count
            member_text = soup.find(string=re.compile(r'members?|subscribers?', re.I))
            
            if member_text:
                numbers = re.findall(r'[\d,]+', member_text)
                if numbers:
                    return int(numbers[0].replace(',', ''))
            
            return 0
    except Exception as e:
        raise Exception(f"Failed to fetch Telegram data: {str(e)}")



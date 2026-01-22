from fastapi import APIRouter, HTTPException, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import PreInfluencer
from app.core.config import settings
from typing import Optional

import httpx


from pydantic import BaseModel
from bs4 import BeautifulSoup
import re
import json

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
        import os
        from dotenv import load_dotenv
        load_dotenv()
        bearer_token = settings.TWITTER_BEARER_TOKEN
        if bearer_token:
            try:
                return await get_twitter_followers_api(username, bearer_token)
            except:
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
    Get Instagram follower count using multiple methods
    Note: Instagram heavily restricts scraping. For production, use Instagram Graph API.
    This function tries multiple methods to extract follower count.
    """
    """
    Get Instagram follower count
    Note: Instagram requires official API access or scraping
    For production, use Instagram Basic Display API or Graph API
    """
    try:
        url = f"https://www.instagram.com/{username}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            html = response.text
            
            soup = BeautifulSoup(html, 'html.parser')
            json_scripts = soup.find_all('script', type='application/ld+json')
            
            for script in json_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and 'mainEntityofPage' in data:
                        interaction_stat = data.get('mainEntityofPage', {}).get('interactionStatistic', {})
                        if 'userInteractionCount' in interaction_stat:
                            count = int(interaction_stat['userInteractionCount'])
                            if count > 0:
                                return count
                except:
                    continue
            
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and ('_sharedData' in script.string or 'profilePage' in script.string):
                    try:
                        json_match = re.search(r'window\._sharedData\s*=\s*({.+?});', script.string, re.DOTALL)
                        if json_match:
                            data = json.loads(json_match.group(1))
                            entry_data = data.get('entry_data', {})
                            profile_page = entry_data.get('ProfilePage', [])
                            if profile_page:
                                user = profile_page[0].get('graphql', {}).get('user', {})
                                edge_followed_by = user.get('edge_followed_by', {})
                                count = edge_followed_by.get('count', 0)
                                if count > 0:
                                    return count
                    except:
                        continue
            
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                property_attr = meta.get('property', '')
                content = meta.get('content', '')
                if 'followers' in property_attr.lower() or 'followers' in content.lower():
                    numbers = re.findall(r'([\d,]+)\s*followers?', content, re.I)
                    if numbers:
                        return int(numbers[0].replace(',', ''))
            
            page_text = soup.get_text()
            patterns = [
                r'([\d,]+)\s*followers?',
                r'([\d.]+[KMB]?)\s*followers?',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, page_text, re.I)
                if matches:
                    count_str = matches[0].replace(',', '').upper()
                    if 'K' in count_str:
                        return int(float(count_str.replace('K', '')) * 1000)
                    elif 'M' in count_str:
                        return int(float(count_str.replace('M', '')) * 1000000)
                    elif 'B' in count_str:
                        return int(float(count_str.replace('B', '')) * 1000000000)
                    else:
                        return int(count_str)
            
            try:
                api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
                api_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'X-IG-App-ID': '936619743392459',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Origin': 'https://www.instagram.com',
                    'Referer': f'https://www.instagram.com/{username}/',
                }
                async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as api_client:
                    api_response = await api_client.get(api_url, headers=api_headers)
                    if api_response.status_code == 200:
                        api_data = api_response.json()
                        user_data = api_data.get('data', {}).get('user', {})
                        edge_followed_by = user_data.get('edge_followed_by', {})
                        count = edge_followed_by.get('count', 0)
                        if count > 0:
                            return count
            except Exception as api_error:
                pass
            
            raise ValueError(
                f"Could not extract follower count for @{username}. "
                "Instagram requires official API access for reliable data. "
                "Please configure INSTAGRAM_ACCESS_TOKEN in .env file. "
                "See README.md for setup instructions."
            )
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to fetch Instagram data: {str(e)}")

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
            
            json_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
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
            
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and ('User' in script.string or 'followers_count' in script.string):
                    try:
                        json_match = re.search(r'"followers_count":\s*(\d+)', script.string)
                        if json_match:
                            count = int(json_match.group(1))
                            if count > 0:
                                return count
                        
                        state_match = re.search(r'__INITIAL_STATE__\s*=\s*({.+?});', script.string, re.DOTALL)
                        if state_match:
                            data = json.loads(state_match.group(1))
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
            
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                property_attr = meta.get('property', '')
                name_attr = meta.get('name', '')
                content = meta.get('content', '')
                
                if 'followers' in property_attr.lower() or 'followers' in name_attr.lower():
                    numbers = re.findall(r'([\d,]+)', content)
                    if numbers:
                        return int(numbers[0].replace(',', ''))
            
            page_text = soup.get_text()
            patterns = [
                r'([\d,]+)\s+[Ff]ollowers?',
                r'([\d.]+[KMB]?)\s+[Ff]ollowers?',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, page_text)
                if matches:
                    count_str = str(matches[0]).replace(',', '').upper()
                    if 'K' in count_str:
                        return int(float(count_str.replace('K', '')) * 1000)
                    elif 'M' in count_str:
                        return int(float(count_str.replace('M', '')) * 1000000)
                    elif 'B' in count_str:
                        return int(float(count_str.replace('B', '')) * 1000000000)
                    else:
                        return int(count_str)
            
            try:
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
                    valid_counts = [m for m in all_matches if 1 <= m <= 1000000000]
                    if valid_counts:
                        from collections import Counter
                        counter = Counter(valid_counts)
                        most_common = counter.most_common(1)[0][0]
                        return most_common
            except:
                pass
            
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
            
            member_text = soup.find(string=re.compile(r'members?|subscribers?', re.I))
            
            if member_text:
                numbers = re.findall(r'[\d,]+', member_text)
                if numbers:
                    return int(numbers[0].replace(',', ''))
            
            return 0
    except Exception as e:
        raise Exception(f"Failed to fetch Telegram data: {str(e)}")



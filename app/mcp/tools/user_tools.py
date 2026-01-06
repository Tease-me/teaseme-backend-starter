"""MCP Tools for User and Billing functionality."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.mcp.server import mcp_server
from app.mcp.types import MCPTool
from app.services.billing import can_afford, get_remaining_units
from app.db.models import User, InfluencerWallet
from sqlalchemy import select
from typing import Any

log = logging.getLogger("mcp.tools.user")


# Tool: Check User Credits
async def check_user_credits_tool(user_id: int, influencer_id: str, feature: str="text", db: AsyncSession=None):
    wallet = await db.scalar(select(InfluencerWallet).where(
        InfluencerWallet.user_id == user_id,
        InfluencerWallet.influencer_id == influencer_id,
    ))
    balance_cents = wallet.balance_cents if wallet else 0

    ok, cost_cents, free_left = await can_afford(db, user_id=user_id, influencer_id=influencer_id, feature=feature, units=1)
    remaining_units = await get_remaining_units(db, user_id, influencer_id, feature)

    return {
        "user_id": user_id,
        "influencer_id": influencer_id,
        "feature": feature,
        "balance_cents": balance_cents,
        "can_afford_one_unit": ok,
        "cost_for_one_unit_cents": cost_cents,
        "free_allowance_remaining": free_left,
        "remaining_units": remaining_units,
    }


CHECK_USER_CREDITS_SCHEMA = MCPTool(
    name="check_user_credits",
    description="Check user's credit balance and availability for a feature",
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "integer",
                "description": "User ID to check credits for"
            },
            "feature": {
                "type": "string",
                "description": "Feature name (text, voice, live_chat)",
                "enum": ["text", "voice", "live_chat"],
                "default": "text"
            }
        },
        "required": ["user_id"]
    }
)


# Tool: Get User Info
async def get_user_info_tool(user_id: int, influencer_id: str, db: AsyncSession=None):
    user = await db.get(User, user_id)
    wallet = await db.scalar(select(InfluencerWallet).where(
        InfluencerWallet.user_id == user_id,
        InfluencerWallet.influencer_id == influencer_id,
    ))
    balance_cents = wallet.balance_cents if wallet else 0
    return {"user_id": user.id, 
            "email": user.email, 
            "influencer_id": influencer_id, 
            "balance_cents": balance_cents
            }

GET_USER_INFO_SCHEMA = MCPTool(
    name="get_user_info",
    description="Get basic user information including credit balance",
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "integer",
                "description": "User ID"
            }
        },
        "required": ["user_id"]
    }
)


# Register tools with MCP server
def register_tools():
    """Register all user tools with the MCP server."""
    mcp_server.register_tool(
        "check_user_credits",
        check_user_credits_tool,
        CHECK_USER_CREDITS_SCHEMA
    )
    mcp_server.register_tool(
        "get_user_info",
        get_user_info_tool,
        GET_USER_INFO_SCHEMA
    )
    log.info("Registered user tools")


# Auto-register on module import
register_tools()

"""MCP Tools for User and Billing functionality."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.mcp.server import mcp_server
from app.mcp.types import MCPTool
from app.db.models import User, InfluencerWallet
from sqlalchemy import select
from typing import Any

log = logging.getLogger("mcp.tools.user")



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
        "get_user_info",
        get_user_info_tool,
        GET_USER_INFO_SCHEMA
    )
    log.info("Registered user tools")


# Auto-register on module import
register_tools()

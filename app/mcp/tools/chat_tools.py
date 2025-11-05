"""MCP Tools for Chat functionality."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.mcp.server import mcp_server
from app.mcp.types import MCPTool
from app.services.chat_service import get_or_create_chat
from sqlalchemy import select, func
from app.db.models import Message, Chat
from typing import Any

log = logging.getLogger("mcp.tools.chat")


# Tool: Get Chat History
async def get_chat_history_tool(
    chat_id: str,
    limit: int = 20,
    page: int = 1,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Get chat message history for a given chat_id.

    Args:
        chat_id: Chat ID
        limit: Maximum number of messages to return (default: 20)
        page: Page number (default: 1)
        db: Database session (injected by dependency)

    Returns:
        Dictionary with messages and pagination info
    """
    if not db:
        raise ValueError("Database session required")

    # Get messages
    offset = (page - 1) * limit
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    messages = result.scalars().all()

    # Get total count
    total_result = await db.execute(
        select(func.count(Message.id)).where(Message.chat_id == chat_id)
    )
    total = total_result.scalar() or 0

    return {
        "chat_id": chat_id,
        "messages": [
            {
                "id": msg.id,
                "sender": msg.sender,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


GET_CHAT_HISTORY_SCHEMA = MCPTool(
    name="get_chat_history",
    description="Get message history for a chat conversation",
    inputSchema={
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "The chat ID to retrieve history for"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of messages to return",
                "default": 20,
                "minimum": 1,
                "maximum": 100
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination",
                "default": 1,
                "minimum": 1
            }
        },
        "required": ["chat_id"]
    }
)


# Tool: Create or Get Chat
async def get_or_create_chat_tool(
    user_id: int,
    influencer_id: str,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Get existing chat or create a new one for user and influencer.

    Args:
        user_id: User ID
        influencer_id: Influencer ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with chat_id
    """
    if not db:
        raise ValueError("Database session required")

    chat_id = await get_or_create_chat(db, user_id, influencer_id)

    # Get chat details
    chat = await db.get(Chat, chat_id)

    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "influencer_id": influencer_id,
        "started_at": chat.started_at.isoformat() if chat and chat.started_at else None,
    }


GET_OR_CREATE_CHAT_SCHEMA = MCPTool(
    name="get_or_create_chat",
    description="Get existing chat or create a new chat between user and influencer",
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "integer",
                "description": "User ID"
            },
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            }
        },
        "required": ["user_id", "influencer_id"]
    }
)


# Register tools with MCP server
def register_tools():
    """Register all chat tools with the MCP server."""
    mcp_server.register_tool(
        "get_chat_history",
        get_chat_history_tool,
        GET_CHAT_HISTORY_SCHEMA
    )
    mcp_server.register_tool(
        "get_or_create_chat",
        get_or_create_chat_tool,
        GET_OR_CREATE_CHAT_SCHEMA
    )
    log.info("Registered chat tools")


# Auto-register on module import
register_tools()

"""MCP Tools for Influencer functionality."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.mcp.server import mcp_server
from app.mcp.types import MCPTool
from app.db.models import Influencer
from sqlalchemy import select
from typing import Any

log = logging.getLogger("mcp.tools.influencer")


# Tool: List Influencers
async def list_influencers_tool(
    limit: int = 50,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    List all available influencers.

    Args:
        limit: Maximum number of influencers to return (default: 50)
        db: Database session (injected by dependency)

    Returns:
        Dictionary with list of influencers
    """
    if not db:
        raise ValueError("Database session required")

    result = await db.execute(
        select(Influencer)
        .limit(limit)
    )
    influencers = result.scalars().all()

    return {
        "influencers": [
            {
                "id": inf.id,
                "display_name": inf.display_name,
                "voice_id": inf.voice_id,
                "created_at": inf.created_at.isoformat() if inf.created_at else None,
            }
            for inf in influencers
        ],
        "count": len(influencers),
    }


LIST_INFLUENCERS_SCHEMA = MCPTool(
    name="list_influencers",
    description="List all available influencers",
    inputSchema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of influencers to return",
                "default": 50,
                "minimum": 1,
                "maximum": 100
            }
        }
    }
)


# Tool: Get Influencer Persona
async def get_influencer_persona_tool(
    influencer_id: str,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Get influencer persona details including prompt template.

    Args:
        influencer_id: Influencer ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with influencer persona information
    """
    if not db:
        raise ValueError("Database session required")

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise ValueError(f"Influencer '{influencer_id}' not found")

    return {
        "id": influencer.id,
        "display_name": influencer.display_name,
        "voice_id": influencer.voice_id,
        "prompt_template": influencer.prompt_template if hasattr(influencer, 'prompt_template') else None,
        "voice_prompt": influencer.voice_prompt if hasattr(influencer, 'voice_prompt') else None,
        "created_at": influencer.created_at.isoformat() if influencer.created_at else None,
    }


GET_INFLUENCER_PERSONA_SCHEMA = MCPTool(
    name="get_influencer_persona",
    description="Get influencer persona details including prompt template",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            }
        },
        "required": ["influencer_id"]
    }
)


# Tool: Update Specific Influencer
async def update_influencer_tool(
    influencer_id: str,
    display_name: str | None = None,
    voice_id: str | None = None,
    prompt_template: str | None = None,
    voice_prompt: str | None = None,
    daily_scripts: list[str] | None = None,
    influencer_agent_id_third_part: str | None = None,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Update a specific influencer's data.

    Args:
        influencer_id: Influencer ID to update
        display_name: Optional new display name
        voice_id: Optional new voice ID
        prompt_template: Optional new prompt template
        voice_prompt: Optional new voice prompt
        daily_scripts: Optional new daily scripts (list of strings)
        influencer_agent_id_third_part: Optional third-party agent ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with updated influencer information
    """
    if not db:
        raise ValueError("Database session required")

    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise ValueError(f"Influencer '{influencer_id}' not found")

    # Update only provided fields
    if display_name is not None:
        influencer.display_name = display_name
    if voice_id is not None:
        influencer.voice_id = voice_id
    if prompt_template is not None:
        influencer.prompt_template = prompt_template
    if voice_prompt is not None:
        influencer.voice_prompt = voice_prompt
    if daily_scripts is not None:
        influencer.daily_scripts = daily_scripts
    if influencer_agent_id_third_part is not None:
        influencer.influencer_agent_id_third_part = influencer_agent_id_third_part

    db.add(influencer)
    await db.commit()
    await db.refresh(influencer)

    return {
        "id": influencer.id,
        "display_name": influencer.display_name,
        "voice_id": influencer.voice_id,
        "prompt_template": influencer.prompt_template if hasattr(influencer, 'prompt_template') else None,
        "voice_prompt": influencer.voice_prompt if hasattr(influencer, 'voice_prompt') else None,
        "daily_scripts": influencer.daily_scripts,
        "influencer_agent_id_third_part": influencer.influencer_agent_id_third_part if hasattr(influencer, 'influencer_agent_id_third_part') else None,
        "updated": True,
    }


UPDATE_INFLUENCER_SCHEMA = MCPTool(
    name="update_influencer",
    description="Update a specific influencer's data (display_name, voice_id, prompt_template, etc.)",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID to update"
            },
            "display_name": {
                "type": "string",
                "description": "New display name (optional)"
            },
            "voice_id": {
                "type": "string",
                "description": "New voice ID (optional)"
            },
            "prompt_template": {
                "type": "string",
                "description": "New prompt template (optional)"
            },
            "voice_prompt": {
                "type": "string",
                "description": "New voice prompt (optional)"
            },
            "daily_scripts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New daily scripts array (optional)"
            },
            "influencer_agent_id_third_part": {
                "type": "string",
                "description": "New third-party agent ID (optional)"
            }
        },
        "required": ["influencer_id"]
    }
)


# Tool: Update All Influencers
async def update_all_influencers_tool(
    display_name: str | None = None,
    voice_id: str | None = None,
    prompt_template: str | None = None,
    voice_prompt: str | None = None,
    daily_scripts: list[str] | None = None,
    influencer_agent_id_third_part: str | None = None,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Update all influencers with the same data.

    Args:
        display_name: Optional new display name to set for all
        voice_id: Optional new voice ID to set for all
        prompt_template: Optional new prompt template to set for all
        voice_prompt: Optional new voice prompt to set for all
        daily_scripts: Optional new daily scripts to set for all
        influencer_agent_id_third_part: Optional third-party agent ID to set for all
        db: Database session (injected by dependency)

    Returns:
        Dictionary with update results
    """
    if not db:
        raise ValueError("Database session required")

    # Get all influencers
    result = await db.execute(select(Influencer))
    influencers = result.scalars().all()

    if not influencers:
        return {
            "updated_count": 0,
            "message": "No influencers found"
        }

    updated_count = 0
    updated_ids = []

    for influencer in influencers:
        updated = False

        # Update only provided fields
        if display_name is not None:
            influencer.display_name = display_name
            updated = True
        if voice_id is not None:
            influencer.voice_id = voice_id
            updated = True
        if prompt_template is not None:
            influencer.prompt_template = prompt_template
            updated = True
        if voice_prompt is not None:
            influencer.voice_prompt = voice_prompt
            updated = True
        if daily_scripts is not None:
            influencer.daily_scripts = daily_scripts
            updated = True
        if influencer_agent_id_third_part is not None:
            influencer.influencer_agent_id_third_part = influencer_agent_id_third_part
            updated = True

        if updated:
            db.add(influencer)
            updated_count += 1
            updated_ids.append(influencer.id)

    if updated_count > 0:
        await db.commit()

    return {
        "updated_count": updated_count,
        "total_influencers": len(influencers),
        "updated_ids": updated_ids,
    }


UPDATE_ALL_INFLUENCERS_SCHEMA = MCPTool(
    name="update_all_influencers",
    description="Update all influencers with the same data (bulk update)",
    inputSchema={
        "type": "object",
        "properties": {
            "display_name": {
                "type": "string",
                "description": "New display name to set for all influencers (optional)"
            },
            "voice_id": {
                "type": "string",
                "description": "New voice ID to set for all influencers (optional)"
            },
            "prompt_template": {
                "type": "string",
                "description": "New prompt template to set for all influencers (optional)"
            },
            "voice_prompt": {
                "type": "string",
                "description": "New voice prompt to set for all influencers (optional)"
            },
            "daily_scripts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New daily scripts array to set for all influencers (optional)"
            },
            "influencer_agent_id_third_part": {
                "type": "string",
                "description": "New third-party agent ID to set for all influencers (optional)"
            }
        }
    }
)


# Register tools with MCP server
def register_tools():
    """Register all influencer tools with the MCP server."""
    mcp_server.register_tool(
        "list_influencers",
        list_influencers_tool,
        LIST_INFLUENCERS_SCHEMA
    )
    mcp_server.register_tool(
        "get_influencer_persona",
        get_influencer_persona_tool,
        GET_INFLUENCER_PERSONA_SCHEMA
    )
    mcp_server.register_tool(
        "update_influencer",
        update_influencer_tool,
        UPDATE_INFLUENCER_SCHEMA
    )
    mcp_server.register_tool(
        "update_all_influencers",
        update_all_influencers_tool,
        UPDATE_ALL_INFLUENCERS_SCHEMA
    )
    log.info("Registered influencer tools")


# Auto-register on module import
register_tools()

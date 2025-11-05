"""MCP FastAPI Router - Exposes MCP endpoints."""

import logging
import inspect
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import mcp_server
from app.mcp.types import ToolCallRequest, ToolCallResponse, MCPPrompt
from app.db.session import get_db

# Import tools to trigger auto-registration
from app.mcp.tools import chat_tools, user_tools, influencer_tools  # noqa: F401

log = logging.getLogger("mcp.router")

router = APIRouter(prefix="/mcp", tags=["mcp"])


class PromptGetRequest(BaseModel):
    """Request to get an MCP prompt."""

    name: str
    arguments: dict[str, Any] | None = None


@router.get("/tools")
async def list_tools():
    """
    List all available MCP tools.

    Returns:
        List of tool definitions
    """
    tools = mcp_server.list_tools()
    return {
        "tools": [tool.model_dump() for tool in tools]
    }


@router.post("/tools/call")
async def call_tool(
    request: ToolCallRequest,
    db: AsyncSession = Depends(get_db)
) -> ToolCallResponse:
    """
    Call an MCP tool.

    Args:
        request: Tool call request with name and arguments
        db: Database session (injected for tools that need it)

    Returns:
        Tool execution result
    """
    tool_data = mcp_server.get_tool(request.name)
    if not tool_data:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{request.name}' not found"
        )

    handler, tool_def = tool_data

    try:
        # Prepare arguments: add db session if tool needs it
        kwargs = request.arguments.copy() if request.arguments else {}
        
        # Check if handler accepts 'db' parameter by inspecting signature
        sig = inspect.signature(handler)
        if 'db' in sig.parameters and 'db' not in kwargs:
            kwargs['db'] = db

        # Call the handler with provided arguments
        if kwargs:
            result = await handler(**kwargs)
        else:
            result = await handler()

        # Format response according to MCP spec
        if isinstance(result, dict):
            return ToolCallResponse(content=result)
        elif isinstance(result, list):
            return ToolCallResponse(content=result)
        else:
            return ToolCallResponse(content={"result": str(result)})

    except Exception as e:
        log.exception(f"Error calling tool '{request.name}': {e}")
        return ToolCallResponse(
            content={"error": str(e)},
            isError=True
        )


@router.get("/resources")
async def list_resources():
    """
    List all available MCP resources.

    Returns:
        List of resource definitions
    """
    resources = mcp_server.list_resources()
    return {
        "resources": [resource.model_dump() for resource in resources]
    }


@router.get("/resources/{uri:path}")
async def get_resource(uri: str):
    """
    Access an MCP resource by URI.

    Args:
        uri: Resource URI (e.g., "chat://chat_id_123")

    Returns:
        Resource content
    """
    resource_data = mcp_server.get_resource(uri)
    if not resource_data:
        raise HTTPException(
            status_code=404,
            detail=f"Resource '{uri}' not found"
        )

    handler, resource_def = resource_data

    try:
        result = await handler(uri)
        return {
            "uri": uri,
            "mimeType": resource_def.mimeType,
            "text": str(result) if not isinstance(result, (dict, list)) else result
        }
    except Exception as e:
        log.exception(f"Error accessing resource '{uri}': {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error accessing resource: {str(e)}"
        )


@router.get("/prompts")
async def list_prompts():
    """
    List all available MCP prompts.

    Returns:
        List of prompt definitions
    """
    prompts = mcp_server.list_prompts()
    return {
        "prompts": [prompt.model_dump() for prompt in prompts]
    }


@router.post("/prompts/get")
async def get_prompt(request: PromptGetRequest) -> dict[str, Any]:
    """
    Get a prompt template with arguments filled in.

    Args:
        request: Prompt request with name and optional arguments

    Returns:
        Generated prompt text
    """
    prompt_data = mcp_server.get_prompt(request.name)
    if not prompt_data:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt '{request.name}' not found"
        )

    handler, prompt_def = prompt_data

    try:
        if request.arguments:
            prompt_text = await handler(**request.arguments)
        else:
            prompt_text = await handler()

        return {
            "name": request.name,
            "description": prompt_def.description,
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt_text
                    }
                }
            ]
        }
    except Exception as e:
        log.exception(f"Error generating prompt '{request.name}': {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating prompt: {str(e)}"
        )

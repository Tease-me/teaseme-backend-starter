"""MCP Protocol Types and Schemas."""

from typing import Any
from pydantic import BaseModel


class MCPTool(BaseModel):
    """MCP Tool definition."""

    name: str
    description: str
    inputSchema: dict[str, Any]


class MCPResource(BaseModel):
    """MCP Resource definition."""

    uri: str
    name: str
    description: str
    mimeType: str | None = None


class MCPPrompt(BaseModel):
    """MCP Prompt template definition."""

    name: str
    description: str
    arguments: list[dict[str, Any]] | None = None


class ToolCallRequest(BaseModel):
    """Request to call an MCP tool."""

    name: str
    arguments: dict[str, Any] | None = None


class ToolCallResponse(BaseModel):
    """Response from calling an MCP tool."""

    content: list[dict[str, Any]] | dict[str, Any] | str
    isError: bool = False

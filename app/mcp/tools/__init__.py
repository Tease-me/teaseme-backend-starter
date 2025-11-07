"""MCP Tools - Register all tools with the MCP server."""

from app.mcp.server import mcp_server

# Import all tool modules to trigger registration
from app.mcp.tools import chat_tools, user_tools, influencer_tools

__all__ = ["chat_tools", "user_tools", "influencer_tools"]

"""MCP Server - Manages tools, resources, and prompts."""

import logging
from typing import Callable, Any, Awaitable
from app.mcp.types import MCPTool, MCPResource, MCPPrompt

log = logging.getLogger("mcp.server")


class MCPServer:
    """MCP Server that registers and manages tools, resources, and prompts."""

    def __init__(self):
        """Initialize MCP Server."""
        self.tools: dict[str, tuple[Callable, MCPTool]] = {}
        self.resources: dict[str, tuple[Callable, MCPResource]] = {}
        self.prompts: dict[str, tuple[Callable, MCPPrompt]] = {}

    def register_tool(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        tool_def: MCPTool,
    ) -> None:
        """
        Register an MCP tool.

        Args:
            name: Tool name (must match tool_def.name)
            handler: Async function that handles the tool call
            tool_def: MCPTool definition with schema
        """
        if name != tool_def.name:
            raise ValueError(f"Tool name mismatch: {name} != {tool_def.name}")

        if name in self.tools:
            log.warning(f"Tool '{name}' already registered, overwriting")

        self.tools[name] = (handler, tool_def)
        log.info(f"Registered MCP tool: {name}")

    def register_resource(
        self,
        uri_pattern: str,
        handler: Callable[..., Awaitable[Any]],
        resource_def: MCPResource,
    ) -> None:
        """
        Register an MCP resource.

        Args:
            uri_pattern: URI pattern (e.g., "chat://*")
            handler: Async function that handles resource access
            resource_def: MCPResource definition
        """
        if uri_pattern in self.resources:
            log.warning(f"Resource '{uri_pattern}' already registered, overwriting")

        self.resources[uri_pattern] = (handler, resource_def)
        log.info(f"Registered MCP resource: {uri_pattern}")

    def register_prompt(
        self,
        name: str,
        handler: Callable[..., Awaitable[str]],
        prompt_def: MCPPrompt,
    ) -> None:
        """
        Register an MCP prompt template.

        Args:
            name: Prompt name (must match prompt_def.name)
            handler: Async function that generates the prompt
            prompt_def: MCPPrompt definition
        """
        if name != prompt_def.name:
            raise ValueError(f"Prompt name mismatch: {name} != {prompt_def.name}")

        if name in self.prompts:
            log.warning(f"Prompt '{name}' already registered, overwriting")

        self.prompts[name] = (handler, prompt_def)
        log.info(f"Registered MCP prompt: {name}")

    def get_tool(self, name: str) -> tuple[Callable, MCPTool] | None:
        """Get a registered tool by name."""
        return self.tools.get(name)

    def get_resource(self, uri: str) -> tuple[Callable, MCPResource] | None:
        """Get a resource handler by URI pattern matching."""
        # Simple exact match for now, can be extended with pattern matching
        return self.resources.get(uri)

    def get_prompt(self, name: str) -> tuple[Callable, MCPPrompt] | None:
        """Get a registered prompt by name."""
        return self.prompts.get(name)

    def list_tools(self) -> list[MCPTool]:
        """List all registered tools."""
        return [tool_def for _, tool_def in self.tools.values()]

    def list_resources(self) -> list[MCPResource]:
        """List all registered resources."""
        return [resource_def for _, resource_def in self.resources.values()]

    def list_prompts(self) -> list[MCPPrompt]:
        """List all registered prompts."""
        return [prompt_def for _, prompt_def in self.prompts.values()]


# Global MCP server instance
mcp_server = MCPServer()

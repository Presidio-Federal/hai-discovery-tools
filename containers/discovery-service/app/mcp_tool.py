"""
HAI Network Discovery Tool - MCP Integration

This module provides a FastMCP tool for network discovery operations,
allowing integration with HAI agents and GitHub runners.
"""

import asyncio
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from fastmcp import Tool, ToolCall, ToolResult

from app.models import DiscoveryConfig
from app.discovery import NetworkDiscovery, DiscoveryMethodRegistry


class DiscoveryInput(BaseModel):
    """Input schema for the discovery tool."""
    seed_devices: List[str] = Field(
        ..., 
        description="List of seed device IPs or hostnames to start discovery from"
    )
    credentials: List[Dict[str, str]] = Field(
        ...,
        description="List of credential sets to try when connecting to devices",
        examples=[[
            {"username": "admin", "password": "password", "enable_secret": "enable"},
            {"username": "netadmin", "password": "netpass"}
        ]]
    )
    method: str = Field(
        default="neighbor_discovery",
        description="Discovery method to use (neighbor_discovery, subnet_scan)"
    )
    max_depth: int = Field(
        default=3,
        description="Maximum depth of discovery from seed devices"
    )
    discovery_protocols: List[str] = Field(
        default=["cdp", "lldp"],
        description="Protocols to use for neighbor discovery"
    )
    timeout: int = Field(
        default=60,
        description="Timeout in seconds for device connections"
    )
    concurrent_connections: int = Field(
        default=10,
        description="Maximum number of concurrent device connections"
    )
    exclude_patterns: List[str] = Field(
        default=[],
        description="Regex patterns for IP addresses to exclude from discovery"
    )


class DiscoveryTool(Tool):
    """Network Discovery Tool for FastMCP integration."""
    
    name = "network_discovery"
    description = "Discovers network devices and extracts their configurations"
    input_schema = DiscoveryInput
    
    async def _run(self, tool_call: ToolCall) -> ToolResult:
        """Run the network discovery process."""
        try:
            # Parse input parameters
            params = DiscoveryInput(**tool_call.parameters)
            
            # Validate discovery method
            if not DiscoveryMethodRegistry.get_method(params.method):
                return ToolResult(
                    tool_call_id=tool_call.id,
                    status="error",
                    error=f"Unknown discovery method: {params.method}"
                )
            
            # Configure discovery
            config = DiscoveryConfig(
                seed_devices=params.seed_devices,
                credentials=params.credentials,
                max_depth=params.max_depth,
                discovery_protocols=params.discovery_protocols,
                timeout=params.timeout,
                concurrent_connections=params.concurrent_connections,
                exclude_patterns=params.exclude_patterns
            )
            
            # Initialize and run discovery
            discovery = NetworkDiscovery(config, params.method)
            result = await discovery.run_discovery()
            
            # Convert to serializable format
            serialized_result = {
                "devices": {ip: device.dict() for ip, device in result.devices.items()},
                "topology": result.topology,
                "stats": {
                    "total_devices": result.total_devices_found,
                    "successful_connections": result.successful_connections,
                    "failed_connections": result.failed_connections,
                    "start_time": result.start_time.isoformat(),
                    "end_time": result.end_time.isoformat() if result.end_time else None
                }
            }
            
            # Return results
            return ToolResult(
                tool_call_id=tool_call.id,
                status="success",
                result=serialized_result
            )
            
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                status="error",
                error=str(e)
            )


class ListDiscoveryMethodsTool(Tool):
    """Tool to list available discovery methods."""
    
    name = "list_discovery_methods"
    description = "Lists available network discovery methods"
    
    async def _run(self, tool_call: ToolCall) -> ToolResult:
        """List available discovery methods."""
        try:
            methods = DiscoveryMethodRegistry.list_methods()
            
            return ToolResult(
                tool_call_id=tool_call.id,
                status="success",
                result={"methods": methods}
            )
            
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                status="error",
                error=str(e)
            )


# Export the tools for FastMCP to discover
tools = [DiscoveryTool(), ListDiscoveryMethodsTool()]

if __name__ == "__main__":
    # This allows the tool to be run directly for testing
    import json
    from fastmcp.cli import run_tool_cli
    
    run_tool_cli(tools)
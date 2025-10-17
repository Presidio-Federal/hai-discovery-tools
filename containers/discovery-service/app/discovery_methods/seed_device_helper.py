"""
Helper functions for extracting information from seed devices.
"""

import asyncio
import re
import logging
from typing import Dict, List, Any, Optional, Set

from app.models import DiscoveryConfig, Credential
from app.device_handler import DeviceHandler

logger = logging.getLogger(__name__)

async def introspect_seed_devices(config: DiscoveryConfig) -> List[str]:
    """
    Log into seed devices and extract subnet information.
    
    Args:
        config: Discovery configuration with seed devices and credentials
        
    Returns:
        List of subnet CIDRs extracted from the devices
    """
    subnets = set()
    device_handler = DeviceHandler(timeout=config.timeout)
    
    for seed_device in config.seed_devices:
        # Parse seed device to get IP and port
        ip_address, port = config.parse_seed_device(seed_device)
        
        # Try each credential
        for credential_dict in config.credentials:
            try:
                # Convert credential dict to Credential object
                credential = Credential(**credential_dict)
                
                # Detect device type
                device_type, _ = await device_handler.detect_device_type(ip_address, credential, port)
                
                if not device_type:
                    logger.warning(f"Could not detect device type for {ip_address}:{port}")
                    continue
                
                # Connect to the device
                conn, _ = await device_handler.connect_to_device(ip_address, credential, device_type, port)
                
                if not conn:
                    logger.warning(f"Could not connect to {ip_address}:{port}")
                    continue
                
                try:
                    # Get interface information
                    interfaces_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show ip interface brief"
                    )
                    
                    # Get routing information
                    routes_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show ip route connected"
                    )
                    
                    # Parse interface output to find IP addresses and subnets
                    interface_subnets = parse_interface_output(interfaces_output)
                    subnets.update(interface_subnets)
                    
                    # Parse route output to find connected subnets
                    route_subnets = parse_route_output(routes_output)
                    subnets.update(route_subnets)
                    
                    logger.info(f"Extracted {len(interface_subnets)} subnets from interfaces and {len(route_subnets)} subnets from routes on {ip_address}")
                    
                finally:
                    # Close the connection
                    conn.disconnect()
                
                # Successfully connected and extracted information, break credential loop
                break
                
            except Exception as e:
                logger.error(f"Error introspecting device {ip_address}:{port}: {str(e)}")
                continue
    
    return list(subnets)

def parse_interface_output(output: str) -> Set[str]:
    """
    Parse 'show ip interface brief' output to extract subnets.
    
    Args:
        output: Command output
        
    Returns:
        Set of subnet CIDRs
    """
    subnets = set()
    
    # Different patterns for different device types
    # Cisco IOS/IOS-XE pattern
    pattern1 = r'(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s+\w+\s+\w+'
    
    # Cisco NXOS pattern
    pattern2 = r'(\S+)\s+(\d+\.\d+\.\d+\.\d+)/(\d+)'
    
    # Find all matches for pattern 1
    for match in re.finditer(pattern1, output):
        ip = match.group(2)
        if ip != "unassigned" and ip != "0.0.0.0":
            # Assume /24 subnet if no mask is provided
            subnets.add(f"{ip}/24")
    
    # Find all matches for pattern 2
    for match in re.finditer(pattern2, output):
        ip = match.group(2)
        prefix = match.group(3)
        subnets.add(f"{ip}/{prefix}")
    
    return subnets

def parse_route_output(output: str) -> Set[str]:
    """
    Parse 'show ip route connected' output to extract subnets.
    
    Args:
        output: Command output
        
    Returns:
        Set of subnet CIDRs
    """
    subnets = set()
    
    # Pattern for connected routes
    pattern = r'C\s+(\d+\.\d+\.\d+\.\d+)/(\d+)'
    
    # Find all matches
    for match in re.finditer(pattern, output):
        network = match.group(1)
        prefix = match.group(2)
        subnets.add(f"{network}/{prefix}")
    
    return subnets

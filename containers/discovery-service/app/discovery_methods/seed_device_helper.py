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

async def introspect_seed_devices(config: DiscoveryConfig) -> Dict[str, Any]:
    """
    Log into seed devices and extract subnet information.
    
    Args:
        config: Discovery configuration with seed devices and credentials
        
    Returns:
        Dictionary with subnets and connected devices information
    """
    subnets = set()
    connected_devices = {}
    device_handler = DeviceHandler(timeout=config.timeout)
    
    for seed_device in config.seed_devices:
        # Parse seed device to get IP and port
        try:
            ip_address, port = config.parse_seed_device(seed_device)
        except Exception as e:
            logger.error(f"Error parsing seed device {seed_device}: {str(e)}")
            continue
        
        # Try each credential
        for credential_dict in config.credentials:
            try:
                # Convert credential dict to Credential object
                credential = Credential(**credential_dict)
                
                # Detect device type
                device_type = await device_handler.detect_device_type(ip_address, credential, port)
                
                if not device_type:
                    logger.warning(f"Could not detect device type for {ip_address}:{port}")
                    continue
                
                # Connect to the device
                conn, detected_type = await device_handler.connect_to_device(ip_address, credential, device_type, port)
                
                if not conn:
                    logger.warning(f"Could not connect to {ip_address}:{port}")
                    continue
                
                try:
                    # Create a device entry for the connected device
                    from app.models import Device, DeviceInterface
                    device_info = Device(
                        hostname=None,  # Will be populated from config
                        ip_address=ip_address,
                        platform=detected_type,
                        device_type=detected_type,
                        discovery_status="discovered",
                        interfaces=[],  # Will be populated later
                        neighbors=[],   # Will be populated later
                        credentials_used={
                            "username": credential.username,
                            "auth_type": credential.auth_type,
                            "port": str(port)
                        }
                    )
                    
                    # Store the device
                    connected_devices[ip_address] = device_info
                    logger.info(f"Successfully connected to seed device {ip_address}:{port}")
                    
                    # Get interface information
                    interfaces_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show ip interface brief"
                    )
                    
                    # Get detailed interface information
                    detailed_interfaces_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show interfaces"
                    )
                    
                    # Get routing information
                    routes_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show ip route connected"
                    )
                    
                    # Get CDP neighbors
                    cdp_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show cdp neighbors detail"
                    )
                    
                    # Get full configuration
                    config_output = await asyncio.get_event_loop().run_in_executor(
                        None, conn.send_command, "show running-config"
                    )
                    
                    # Store the configuration in the device info
                    if ip_address in connected_devices and config_output:
                        # Check if device_info is a Device object or a dict
                        if hasattr(connected_devices[ip_address], 'config'):
                            connected_devices[ip_address].config = config_output
                            
                            # Extract hostname from config
                            hostname_match = re.search(r'hostname\s+(\S+)', config_output)
                            if hostname_match:
                                connected_devices[ip_address].hostname = hostname_match.group(1)
                        elif isinstance(connected_devices[ip_address], dict):
                            connected_devices[ip_address]['config'] = config_output
                        else:
                            logger.warning(f"Cannot store config for {ip_address}: unexpected device info type {type(connected_devices[ip_address])}")
                    
                    # Parse interfaces from interface output
                    if ip_address in connected_devices:
                        # Extract interfaces from brief output
                        interfaces = []
                        interface_lines = interfaces_output.strip().split('\n')
                        
                        # Skip header line
                        if len(interface_lines) > 1:
                            for line in interface_lines[1:]:
                                parts = line.split()
                                if len(parts) >= 2:
                                    intf_name = parts[0]
                                    intf_ip = parts[1]
                                    
                                    if intf_ip == "unassigned" or intf_ip == "0.0.0.0":
                                        intf_ip = None
                                    
                                    status = "up" if len(parts) >= 5 and parts[4] == "up" else "down"
                                    
                                    # Create interface object
                                    intf = DeviceInterface(
                                        name=intf_name,
                                        ip_address=intf_ip,
                                        status=status
                                    )
                                    
                                    # Extract subnet mask from detailed interface output
                                    # Try multiple patterns to match different output formats
                                    mask_match = None
                                    
                                    # Pattern 1: Internet address is x.x.x.x/prefix
                                    mask_match = re.search(f"{intf_name}.*?Internet address is.*?/(\\d+)", detailed_interfaces_output, re.DOTALL)
                                    
                                    # Pattern 2: Internet address is x.x.x.x subnet_mask
                                    if not mask_match:
                                        ip_mask_match = re.search(f"{intf_name}.*?Internet address is\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)", detailed_interfaces_output, re.DOTALL)
                                        if ip_mask_match:
                                            intf.subnet_mask = ip_mask_match.group(2)
                                    
                                    # Pattern 3: For loopback interfaces, default to /32 (255.255.255.255)
                                    if not mask_match and not intf.subnet_mask and intf_name.lower().startswith("loopback"):
                                        intf.subnet_mask = "255.255.255.255"
                                        logger.info(f"Applied /32 (255.255.255.255) subnet mask to loopback interface {intf_name}")
                                    
                                    # Process prefix match if found
                                    if mask_match:
                                        prefix = mask_match.group(1)
                                        # Convert prefix to subnet mask
                                        import ipaddress
                                        try:
                                            mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
                                            intf.subnet_mask = mask
                                        except:
                                            # If conversion fails, default to /32 for safety
                                            if intf_name.lower().startswith("loopback"):
                                                intf.subnet_mask = "255.255.255.255"
                                                logger.info(f"Failed to convert prefix, applied /32 (255.255.255.255) subnet mask to loopback interface {intf_name}")
                                    
                                    # If still no subnet mask, default to /32 for all interfaces as a guardrail
                                    if not intf.subnet_mask and intf.ip_address:
                                        intf.subnet_mask = "255.255.255.255"
                                        logger.info(f"Applied guardrail /32 (255.255.255.255) subnet mask to interface {intf_name} with IP {intf.ip_address}")
                                    
                                    # Extract description from detailed interface output
                                    desc_match = re.search(f"{intf_name}.*?Description: (.*?)\\n", detailed_interfaces_output, re.DOTALL)
                                    if desc_match:
                                        intf.description = desc_match.group(1).strip()
                                    
                                    interfaces.append(intf)
                        
                        # Add interfaces to device
                        connected_devices[ip_address].interfaces = interfaces
                        
                        # Collect all IP addresses from interfaces
                        all_ips = [ip_address]  # Start with the primary IP
                        for intf in interfaces:
                            if intf.ip_address and intf.ip_address not in ["unassigned", "0.0.0.0", "dhcp"] and intf.ip_address not in all_ips:
                                all_ips.append(intf.ip_address)
                        
                        # Update all_ip_addresses field
                        connected_devices[ip_address].all_ip_addresses = all_ips
                        
                        logger.info(f"Added {len(interfaces)} interfaces to device {ip_address}")
                        
                    # Parse CDP neighbors
                    if ip_address in connected_devices and cdp_output:
                        try:
                            from app.parsers.cdp_parser import CDPParser
                            neighbors = CDPParser.parse(cdp_output)
                            if neighbors:
                                connected_devices[ip_address].neighbors = neighbors
                                logger.info(f"Added {len(neighbors)} neighbors to device {ip_address}")
                        except Exception as e:
                            logger.warning(f"Error parsing CDP output: {str(e)}")
                            # Continue without neighbors
                            connected_devices[ip_address].neighbors = []
                    
                    # Parse interface output to find IP addresses, subnets, and loopback IPs
                    interface_subnets, loopback_ips = parse_interface_output(interfaces_output)
                    subnets.update(interface_subnets)
                    
                    # Parse route output to find connected subnets
                    route_subnets = parse_route_output(routes_output)
                    subnets.update(route_subnets)
                    
                    logger.info(f"Extracted {len(interface_subnets)} subnets from interfaces and {len(route_subnets)} subnets from routes on {ip_address}")
                    
                    # Add loopback IPs as seed devices to try
                    if loopback_ips:
                        logger.info(f"Found {len(loopback_ips)} loopback IPs on {ip_address}: {', '.join(loopback_ips)}")
                        
                        # Add loopback IPs to the device's all_ip_addresses
                        if hasattr(device_info, 'all_ip_addresses'):
                            for loopback_ip in loopback_ips:
                                if loopback_ip not in device_info.all_ip_addresses:
                                    device_info.all_ip_addresses.append(loopback_ip)
                                    logger.info(f"Added loopback IP {loopback_ip} to device {ip_address} all_ip_addresses")
                        
                        # Add loopback IPs as specific subnets to scan
                        for loopback_ip in loopback_ips:
                            subnets.add(f"{loopback_ip}/32")
                            logger.info(f"Added loopback IP {loopback_ip}/32 as a subnet to scan")
                    
                finally:
                    # Close the connection
                    conn.disconnect()
                
                # Successfully connected and extracted information, break credential loop
                break
                
            except Exception as e:
                logger.error(f"Error introspecting device {ip_address}:{port}: {str(e)}")
                continue
    
    return {
        "subnets": list(subnets),
        "devices": connected_devices
    }

def parse_interface_output(output: str) -> tuple[Set[str], Set[str]]:
    """
    Parse 'show ip interface brief' output to extract subnets and loopback IPs.
    
    Args:
        output: Command output
        
    Returns:
        Tuple of (subnet CIDRs, loopback IPs)
    """
    subnets = set()
    loopback_ips = set()
    
    # Different patterns for different device types
    # Cisco IOS/IOS-XE pattern
    pattern1 = r'(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s+\w+\s+\w+'
    
    # Cisco NXOS pattern
    pattern2 = r'(\S+)\s+(\d+\.\d+\.\d+\.\d+)/(\d+)'
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Find all matches for pattern 1
    for match in re.finditer(pattern1, output):
        interface_name = match.group(1)
        ip = match.group(2)
        if ip != "unassigned" and ip != "0.0.0.0" and ip != "dhcp":
            # For interfaces with IP addresses, add the host address
            subnets.add(f"{ip}/32")  # Add the host address
            
            # Check if this is a loopback interface
            if interface_name.lower().startswith("loopback"):
                loopback_ips.add(ip)
                logger.info(f"Found loopback IP: {ip} on {interface_name}")
            
            # Log what we're adding
            logger.info(f"Added host IP {ip}/32 from interface output")
    
    # Find all matches for pattern 2
    for match in re.finditer(pattern2, output):
        interface_name = match.group(1)
        ip = match.group(2)
        prefix = match.group(3)
        subnets.add(f"{ip}/{prefix}")
        
        # Check if this is a loopback interface
        if interface_name.lower().startswith("loopback"):
            loopback_ips.add(ip)
            logger.info(f"Found loopback IP: {ip} on {interface_name}")
        
        # Log the subnet we found
        logger.info(f"Added subnet {ip}/{prefix} from interface output")
    
    return subnets, loopback_ips

def parse_route_output(output: str) -> Set[str]:
    """
    Parse 'show ip route connected' output to extract subnets.
    
    Args:
        output: Command output
        
    Returns:
        Set of subnet CIDRs
    """
    subnets = set()
    
    # Pattern for connected routes - look for both C and L routes and various formats
    patterns = [
        r'[CL]\s+(\d+\.\d+\.\d+\.\d+)/(\d+)',  # Standard format: C 10.0.0.0/24
        r'[CL]\s+(\d+\.\d+\.\d+\.\d+)\s+is\s+\w+\s+connected',  # Alternate format: C 10.0.0.0 is directly connected
        r'(\d+\.\d+\.\d+\.\d+)/(\d+)\s+is\s+\w+\s+connected'  # Another format: 10.0.0.0/24 is directly connected
    ]
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Process each pattern
    for pattern in patterns:
        for match in re.finditer(pattern, output):
            if len(match.groups()) >= 2:
                # Standard format with network and prefix
                network = match.group(1)
                prefix = match.group(2)
                subnet = f"{network}/{prefix}"
            elif len(match.groups()) == 1:
                # Format with just network, assume /24
                network = match.group(1)
                subnet = f"{network}/24"
                logger.info(f"Found connected route without prefix: {network}, assuming /24")
            else:
                continue
            
            # Add the subnet
            subnets.add(subnet)
            
            # Log the subnet we found
            logger.info(f"Added subnet {subnet} from route output")
            
            # Also add a /32 for the IP itself
            subnets.add(f"{network}/32")
            logger.info(f"Added host IP {network}/32 from route output")
    
            # If we didn't find any subnets but the output contains "directly connected",
    # try a more aggressive pattern
    if not subnets and "connected" in output:
        ip_pattern = r'(\d+\.\d+\.\d+\.\d+)'
        for match in re.finditer(ip_pattern, output):
            ip = match.group(1)
            if ip != "0.0.0.0" and ip != "255.255.255.255":
                # Add the IP as a /32 - GUARDRAIL: Default to /32 instead of broader subnets
                host_subnet = f"{ip}/32"
                subnets.add(host_subnet)
                logger.info(f"Added host IP {host_subnet} from route output as a guardrail (defaulting to /32)")
    
    return subnets

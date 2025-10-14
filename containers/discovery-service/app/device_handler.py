"""
Unified device handler for network discovery.

This module provides a unified interface for interacting with network devices
using Netmiko's built-in multi-vendor capabilities.
"""

import asyncio
import logging
import re
import socket
from typing import Dict, List, Any, Optional, Tuple

import netmiko
from netmiko import ConnectHandler
from netmiko.ssh_autodetect import SSHDetect

from app.models import Credential, DeviceInterface, Device
from app.parsers.cdp_parser import CDPParser
from app.parsers.lldp_parser import LLDPParser
from app.parsers.config_parser import ConfigParser

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeviceHandler:
    """Unified handler for network device interactions."""
    
    # Command mappings for different device types
    # These are fallbacks if the standard commands don't work
    COMMAND_MAPPINGS = {
        # Common commands that work across most platforms
        "default": {
            "version": "show version",
            "config": "show running-config",
            "interfaces": "show interfaces",
            "cdp_neighbors": "show cdp neighbors detail",
            "lldp_neighbors": "show lldp neighbors detail",
            "hostname": "show hostname",
        },
        # Cisco IOS specific commands
        "cisco_ios": {
            "version": "show version",
            "config": "show running-config",
            "interfaces": "show interfaces",
            "cdp_neighbors": "show cdp neighbors detail",
            "lldp_neighbors": "show lldp neighbors detail",
            "hostname": "show hostname",
            "inventory": "show inventory",
            "vlan": "show vlan brief",
        },
        # Cisco NXOS specific commands
        "cisco_nxos": {
            "version": "show version",
            "config": "show running-config",
            "interfaces": "show interface",
            "cdp_neighbors": "show cdp neighbors detail",
            "lldp_neighbors": "show lldp neighbors detail",
            "hostname": "show hostname",
            "inventory": "show inventory",
        },
        # Juniper Junos specific commands
        "juniper_junos": {
            "version": "show version",
            "config": "show configuration | display set",
            "interfaces": "show interfaces",
            "lldp_neighbors": "show lldp neighbors",
            "hostname": "show system information | match Hostname",
            "inventory": "show chassis hardware",
        },
        # Arista EOS specific commands
        "arista_eos": {
            "version": "show version",
            "config": "show running-config",
            "interfaces": "show interfaces",
            "cdp_neighbors": "show cdp neighbors detail",
            "lldp_neighbors": "show lldp neighbors detail",
            "hostname": "show hostname",
            "inventory": "show inventory",
        },
    }
    
    def __init__(self, timeout: int = 60):
        """Initialize device handler with timeout setting."""
        self.timeout = timeout
    
    async def detect_device_type(self, ip_address: str, credential: Credential, port: int = 22) -> Optional[str]:
        """
        Detect the device type using Netmiko's SSHDetect.
        
        Returns the detected device_type or None if detection fails.
        """
        try:
            logger.info(f"Starting device type detection for {ip_address}:{port}")
            
            # Check if SSH port is open first
            if not await self._check_port_open(ip_address, port):
                logger.error(f"SSH port {port} not open on {ip_address}")
                return None
            
            # Use Netmiko's built-in autodetection
            device_params = {
                'device_type': 'autodetect',
                'host': ip_address,
                'port': port,
                'username': credential.username,
                'password': credential.password,
                'timeout': self.timeout,
            }
            
            if credential.enable_secret:
                device_params['secret'] = credential.enable_secret
            
            logger.info(f"SSH port {port} is open on {ip_address}. Attempting autodetection with username {credential.username}")
            
            loop = asyncio.get_event_loop()
            device_type = await loop.run_in_executor(
                None,
                self._run_autodetect,
                device_params
            )
            
            if device_type:
                logger.info(f"Successfully detected device type for {ip_address}:{port}: {device_type}")
            else:
                logger.error(f"Failed to detect device type for {ip_address}:{port}")
                
            return device_type
            
        except (netmiko.exceptions.NetmikoTimeoutException, socket.timeout) as e:
            logger.error(f"Connection timeout while detecting device type for {ip_address}:{port}: {str(e)}")
            return None
            
        except netmiko.exceptions.NetmikoAuthenticationException as e:
            logger.error(f"Authentication failed while detecting device type for {ip_address}:{port}: {str(e)}")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting device type for {ip_address}:{port}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def _run_autodetect(self, device_params: Dict[str, Any]) -> Optional[str]:
        """Run Netmiko's autodetection (must be run in executor)."""
        try:
            logger.info(f"Starting SSH autodetect for {device_params['host']}:{device_params['port']}")
            ssh_detect = SSHDetect(**device_params)
            device_type = ssh_detect.autodetect()
            logger.info(f"Autodetect result for {device_params['host']}:{device_params['port']}: {device_type}")
            return device_type
        except Exception as e:
            logger.error(f"Autodetect error for {device_params['host']}:{device_params['port']}: {str(e)}")
            import traceback
            logger.error(f"Autodetect traceback: {traceback.format_exc()}")
            return None
    
    async def _check_port_open(self, ip_address: str, port: int) -> bool:
        """Check if a TCP port is open."""
        try:
            logger.info(f"Checking if port {port} is open on {ip_address}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)  # Increase timeout for more reliable checks
            
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, sock.connect, (ip_address, port))
                sock.close()
                logger.info(f"Port {port} is open on {ip_address}")
                return True
            except socket.timeout:
                logger.error(f"Connection to {ip_address}:{port} timed out")
                return False
            except ConnectionRefusedError:
                logger.error(f"Connection to {ip_address}:{port} refused")
                return False
            
        except (socket.timeout, ConnectionRefusedError) as e:
            logger.error(f"Error checking port {port} on {ip_address}: {str(e)}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error checking port {port} on {ip_address}: {str(e)}")
            import traceback
            logger.error(f"Port check traceback: {traceback.format_exc()}")
            return False
    
    async def connect_to_device(self, ip_address: str, credential: Credential, 
                              device_type: Optional[str] = None, port: int = 22) -> Tuple[Optional[Any], Optional[str]]:
        """
        Connect to a device using Netmiko.
        
        Returns a tuple of (connection, device_type) or (None, None) if connection fails.
        """
        try:
            # If device_type not provided, try to detect it
            if not device_type:
                device_type = await self.detect_device_type(ip_address, credential, port)
            
            # If we still don't have a device type, use cisco_ios as fallback
            if not device_type:
                device_type = 'cisco_ios'  # Most common fallback
            
            # Prepare connection parameters
            device_params = {
                'device_type': device_type,
                'host': ip_address,
                'port': port,
                'username': credential.username,
                'password': credential.password,
                'timeout': self.timeout,
            }
            
            if credential.enable_secret:
                device_params['secret'] = credential.enable_secret
                
            logger.info(f"Connecting to {ip_address}:{port} with device_type {device_type}")
            
            # Connect to device with a timeout
            loop = asyncio.get_event_loop()
            try:
                conn = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: ConnectHandler(**device_params)
                    ),
                    timeout=self.timeout
                )
                logger.info(f"Successfully connected to {ip_address}:{port}")
                return conn, device_type
            except asyncio.TimeoutError:
                logger.error(f"Connection to {ip_address}:{port} timed out after {self.timeout} seconds")
                return None, None
            
        except (netmiko.exceptions.NetmikoTimeoutException, socket.timeout) as e:
            logger.error(f"Netmiko timeout connecting to {ip_address}:{port}: {str(e)}")
            return None, None
            
        except netmiko.exceptions.NetmikoAuthenticationException as e:
            logger.error(f"Authentication failed for {ip_address}:{port}: {str(e)}")
            return None, None
            
        except Exception as e:
            logger.error(f"Error connecting to {ip_address}:{port}: {str(e)}")
            import traceback
            logger.error(f"Connection traceback: {traceback.format_exc()}")
            return None, None
    
    async def get_device_info(self, ip_address: str, credential: Credential, 
                            device_type: Optional[str] = None, port: int = 22) -> Dict[str, Any]:
        """Get basic device information."""
        device_info = {}
        
        # Connect to the device
        conn, detected_type = await self.connect_to_device(ip_address, credential, device_type, port)
        if not conn:
            return device_info
        
        device_type = detected_type  # Use the detected type
        
        try:
            loop = asyncio.get_event_loop()
            
            # Get running config first - we'll use this for more reliable parsing
            config_cmd = self._get_command("config", device_type)
            logger.info(f"Getting configuration from {ip_address}:{port} using command: {config_cmd}")
            config_output = await loop.run_in_executor(None, conn.send_command, config_cmd)
            
            # Get hostname from config
            hostname_match = re.search(r"hostname\s+(\S+)", config_output, re.IGNORECASE)
            if hostname_match:
                device_info["hostname"] = hostname_match.group(1)
                logger.info(f"Extracted hostname '{device_info['hostname']}' from config for {ip_address}:{port}")
            else:
                # Fallback to hostname command
                hostname_cmd = self._get_command("hostname", device_type)
                logger.info(f"Getting hostname from {ip_address}:{port} using command: {hostname_cmd}")
                hostname_output = await loop.run_in_executor(None, conn.send_command, hostname_cmd)
                device_info["hostname"] = self._extract_hostname(hostname_output, device_type)
                logger.info(f"Extracted hostname '{device_info['hostname']}' from command output for {ip_address}:{port}")
            
            # Get version information
            version_cmd = self._get_command("version", device_type)
            version_output = await loop.run_in_executor(None, conn.send_command, version_cmd)
            
            # Extract version info based on device type
            device_info["platform"] = device_type.split('_')[0] if '_' in device_type else device_type
            device_info["os_version"] = self._extract_version_info(version_output, device_type)
            device_info["model"] = self._extract_model_info(version_output, device_type)
            device_info["serial_number"] = self._extract_serial_info(version_output, device_type)
            
            # Parse interfaces from config
            logger.info(f"Parsing interfaces from config for {ip_address}:{port}")
            device_info["interfaces"] = self._parse_interfaces_from_config(config_output, device_type)
            logger.info(f"Found {len(device_info['interfaces'])} interfaces from config for {ip_address}:{port}")
            
            # If no interfaces found in config, try the show interfaces command
            if not device_info["interfaces"]:
                logger.info(f"No interfaces found in config, trying show interfaces command for {ip_address}:{port}")
                interfaces_cmd = self._get_command("interfaces", device_type)
                interfaces_output = await loop.run_in_executor(None, conn.send_command, interfaces_cmd)
                device_info["interfaces"] = self._parse_interfaces(interfaces_output, device_type)
                logger.info(f"Found {len(device_info['interfaces'])} interfaces from command for {ip_address}:{port}")
                
            # Log interface details for debugging
            for intf in device_info["interfaces"]:
                if hasattr(intf, 'name') and hasattr(intf, 'ip_address'):
                    logger.info(f"Interface {intf.name}: IP={intf.ip_address or 'None'}, Status={getattr(intf, 'status', 'Unknown')}")
            
            return device_info
            
        except Exception as e:
            logger.error(f"Error getting device info for {ip_address}: {str(e)}")
            return device_info
            
        finally:
            # Ensure connection is closed
            try:
                await loop.run_in_executor(None, conn.disconnect)
            except Exception:
                pass
    
    async def get_device_config(self, ip_address: str, credential: Credential, 
                              device_type: Optional[str] = None, port: int = 22) -> Dict[str, Any]:
        """Get device configuration."""
        result = {
            "raw_config": None,
            "parsed_config": None
        }
        
        # Connect to the device
        conn, detected_type = await self.connect_to_device(ip_address, credential, device_type, port)
        if not conn:
            return result
        
        device_type = detected_type  # Use the detected type
        
        try:
            loop = asyncio.get_event_loop()
            
            # Get running config
            config_cmd = self._get_command("config", device_type)
            config_output = await loop.run_in_executor(None, conn.send_command, config_cmd)
            result["raw_config"] = config_output
            
            # Parse config using ConfigParser
            config_parser = ConfigParser()
            result["parsed_config"] = config_parser.parse(config_output, device_type)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting device config for {ip_address}: {str(e)}")
            return result
            
        finally:
            # Ensure connection is closed
            try:
                await loop.run_in_executor(None, conn.disconnect)
            except Exception:
                pass
    
    async def get_device_neighbors(self, ip_address: str, credential: Credential, 
                                 protocols: List[str], device_type: Optional[str] = None, 
                                 port: int = 22) -> List[Dict[str, Any]]:
        """Get device neighbors using CDP/LLDP."""
        neighbors = []
        
        # Connect to the device
        conn, detected_type = await self.connect_to_device(ip_address, credential, device_type, port)
        if not conn:
            return neighbors
        
        device_type = detected_type  # Use the detected type
        
        try:
            loop = asyncio.get_event_loop()
            
            # Check CDP neighbors
            if "cdp" in protocols:
                logger.info(f"Getting CDP neighbors for {ip_address}:{port}")
                cdp_cmd = self._get_command("cdp_neighbors", device_type)
                cdp_output = await loop.run_in_executor(None, conn.send_command, cdp_cmd)
                
                # Parse CDP output
                cdp_parser = CDPParser()
                cdp_neighbors = cdp_parser.parse_cdp_output(cdp_output, device_type)
                if cdp_neighbors:
                    neighbors.extend(cdp_neighbors)
                    logger.info(f"Found {len(cdp_neighbors)} CDP neighbors for {ip_address}:{port}")
            
            # Check LLDP neighbors
            if "lldp" in protocols:
                logger.info(f"Getting LLDP neighbors for {ip_address}:{port}")
                lldp_cmd = self._get_command("lldp_neighbors", device_type)
                lldp_output = await loop.run_in_executor(None, conn.send_command, lldp_cmd)
                
                # Parse LLDP output
                lldp_parser = LLDPParser()
                lldp_neighbors = lldp_parser.parse(lldp_output, device_type)
                if lldp_neighbors:
                    neighbors.extend(lldp_neighbors)
                    logger.info(f"Found {len(lldp_neighbors)} LLDP neighbors for {ip_address}:{port}")
            
            return neighbors
            
        except Exception as e:
            logger.error(f"Error getting device neighbors for {ip_address}: {str(e)}")
            return neighbors
            
        finally:
            # Ensure connection is closed
            try:
                await loop.run_in_executor(None, conn.disconnect)
            except Exception:
                pass
    
    def _get_command(self, command_type: str, device_type: str) -> str:
        """Get the appropriate command for the device type."""
        # Check if we have specific commands for this device type
        if device_type in self.COMMAND_MAPPINGS and command_type in self.COMMAND_MAPPINGS[device_type]:
            return self.COMMAND_MAPPINGS[device_type][command_type]
        
        # Fall back to default commands
        if command_type in self.COMMAND_MAPPINGS["default"]:
            return self.COMMAND_MAPPINGS["default"][command_type]
        
        # If all else fails, return the command type as is
        return command_type
    
    def _extract_hostname(self, output: str, device_type: str) -> Optional[str]:
        """Extract hostname from command output."""
        if not output:
            return None
            
        # First try to extract from show running-config
        if "hostname" in output.lower():
            match = re.search(r"hostname\s+(\S+)", output, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # For Cisco IOS/NXOS, if not an error message
        if device_type in ["cisco_ios", "cisco_nxos", "arista_eos", "cisco_xe"]:
            # Check if the output is an error message
            if not output.startswith("^") and not "% Invalid" in output:
                return output.strip()
            
        # For Juniper
        if device_type == "juniper_junos":
            match = re.search(r"Hostname:\s+(\S+)", output)
            if match:
                return match.group(1)
                
        # Generic extraction - try to find the hostname
        match = re.search(r"hostname[:\s]+(\S+)", output, re.IGNORECASE)
        if match:
            return match.group(1)
            
        # If all else fails, check if the raw output is a valid hostname
        clean_output = output.strip()
        if clean_output and not clean_output.startswith("^") and not "% Invalid" in clean_output:
            return clean_output
            
        return None
    
    def _extract_version_info(self, output: str, device_type: str) -> Optional[str]:
        """Extract OS version from show version output."""
        if not output:
            return None
            
        # For Cisco IOS
        if device_type == "cisco_ios":
            match = re.search(r"Cisco IOS.+Version ([^,]+),", output)
            if match:
                return match.group(1)
                
        # For Cisco NXOS
        if device_type == "cisco_nxos":
            match = re.search(r"NXOS: version ([^\s]+)", output)
            if match:
                return match.group(1)
                
        # For Juniper
        if device_type == "juniper_junos":
            match = re.search(r"JUNOS\s+([^\s]+)", output)
            if match:
                return match.group(1)
                
        # For Arista
        if device_type == "arista_eos":
            match = re.search(r"EOS version: ([\d\.]+)", output)
            if match:
                return match.group(1)
                
        # Generic version extraction
        match = re.search(r"[vV]ersion:?\s+(\S+)", output)
        if match:
            return match.group(1)
            
        return None
    
    def _extract_model_info(self, output: str, device_type: str) -> Optional[str]:
        """Extract model information from show version output."""
        if not output:
            return None
            
        # For Cisco IOS
        if device_type == "cisco_ios":
            match = re.search(r"[Cc]isco ([\w-]+).+processor", output)
            if match:
                return match.group(1)
                
        # For Cisco NXOS
        if device_type == "cisco_nxos":
            match = re.search(r"cisco Nexus(\S+)", output)
            if match:
                return f"Nexus{match.group(1)}"
                
        # For Juniper
        if device_type == "juniper_junos":
            match = re.search(r"Model: ([\w-]+)", output)
            if match:
                return match.group(1)
                
        # For Arista
        if device_type == "arista_eos":
            match = re.search(r"Hardware model: ([\w-]+)", output)
            if match:
                return match.group(1)
                
        # Generic model extraction
        match = re.search(r"[mM]odel:?\s+(\S+)", output)
        if match:
            return match.group(1)
            
        return None
    
    def _extract_serial_info(self, output: str, device_type: str) -> Optional[str]:
        """Extract serial number from show version output."""
        if not output:
            return None
            
        # For Cisco IOS
        if device_type == "cisco_ios":
            match = re.search(r"Processor board ID (\w+)", output)
            if match:
                return match.group(1)
                
        # For Cisco NXOS
        if device_type == "cisco_nxos":
            match = re.search(r"Processor Board ID (\w+)", output)
            if match:
                return match.group(1)
                
        # For Juniper
        if device_type == "juniper_junos":
            match = re.search(r"Chassis\s+(\w+)", output)
            if match:
                return match.group(1)
                
        # For Arista
        if device_type == "arista_eos":
            match = re.search(r"Serial number: (\w+)", output)
            if match:
                return match.group(1)
                
        # Generic serial extraction
        match = re.search(r"[sS]erial:?\s+(\S+)", output)
        if match:
            return match.group(1)
            
        return None
    
    def _parse_interfaces_from_config(self, config: str, device_type: str) -> List[DeviceInterface]:
        """Parse interface information from running configuration."""
        interfaces = []
        
        if not config:
            return interfaces
            
        logger.info(f"Parsing interfaces from config for device type: {device_type}")
        
        # For Cisco IOS/NXOS/XE
        if device_type in ["cisco_ios", "cisco_nxos", "cisco_xe"]:
            # Extract interface sections from config - improved pattern to better match Cisco configs
            interface_pattern = r"^interface\s+([^\n]+)[\r\n]+((?:.+?(?:\n|$))+?)(?=^!|\Z)"
            try:
                interface_matches = list(re.finditer(interface_pattern, config, re.MULTILINE | re.DOTALL))
                logger.info(f"Found {len(interface_matches)} interface sections in config")
            except Exception as e:
                logger.error(f"Error in regex pattern: {str(e)}")
                interface_matches = []
            
            for match in interface_matches:
                name = match.group(1).strip()
                config_section = match.group(2).strip()
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Extract IP address - handle both standard and DHCP formats
                ip_match = re.search(r"ip address ([\d\.]+) ([\d\.]+)", config_section)
                dhcp_match = re.search(r"ip address dhcp", config_section)
                secondary_ip_matches = re.finditer(r"ip address ([\d\.]+) ([\d\.]+) secondary", config_section)
                
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                    interface.subnet_mask = ip_match.group(2)
                    logger.info(f"Found IP address {interface.ip_address} for interface {name}")
                    
                    # Store secondary IPs in a list
                    secondary_ips = []
                    for sec_match in secondary_ip_matches:
                        secondary_ips.append({
                            "ip": sec_match.group(1),
                            "mask": sec_match.group(2)
                        })
                    if secondary_ips:
                        interface.secondary_ips = secondary_ips
                        logger.info(f"Found {len(secondary_ips)} secondary IPs for interface {name}")
                elif dhcp_match:
                    interface.ip_address = "dhcp"
                    logger.info(f"Interface {name} is using DHCP")
                
                # Extract description
                desc_match = re.search(r"description (.+?)$", config_section, re.MULTILINE)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                if "shutdown" in config_section:
                    interface.status = "down"
                else:
                    interface.status = "up"
                
                # Extract VLAN information
                vlan_match = re.search(r"switchport access vlan (\d+)", config_section)
                if vlan_match:
                    interface.vlan = vlan_match.group(1)
                    
                # Check if trunk
                if "switchport mode trunk" in config_section:
                    interface.is_trunk = True
                
                logger.info(f"Adding interface {name} with status {interface.status}")
                interfaces.append(interface)
        
        # For Juniper
        elif device_type == "juniper_junos":
            # TODO: Add Juniper config parsing
            pass
            
        # For Arista
        elif device_type == "arista_eos":
            # Similar to Cisco but with Arista-specific pattern
            interface_pattern = r"^interface\s+([^\n]+)[\r\n]+((?:.+?(?:\n|$))+?)(?=^!|\Z)"
            interface_matches = re.finditer(interface_pattern, config, re.MULTILINE | re.DOTALL)
            
            for match in interface_matches:
                name = match.group(1).strip()
                config_section = match.group(2).strip()
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Extract IP address - handle both standard and CIDR formats
                ip_match = re.search(r"ip address ([\d\.]+)/(\d+)", config_section)
                standard_match = re.search(r"ip address ([\d\.]+) ([\d\.]+)", config_section)
                dhcp_match = re.search(r"ip address dhcp", config_section)
                
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                    # Convert CIDR to subnet mask
                    cidr = int(ip_match.group(2))
                    mask_int = (0xffffffff << (32 - cidr)) & 0xffffffff
                    interface.subnet_mask = f"{mask_int >> 24 & 0xff}.{mask_int >> 16 & 0xff}.{mask_int >> 8 & 0xff}.{mask_int & 0xff}"
                    logger.info(f"Found IP address {interface.ip_address} with CIDR /{cidr} for interface {name}")
                elif standard_match:
                    interface.ip_address = standard_match.group(1)
                    interface.subnet_mask = standard_match.group(2)
                    logger.info(f"Found IP address {interface.ip_address} for interface {name}")
                elif dhcp_match:
                    interface.ip_address = "DHCP"
                    logger.info(f"Found DHCP configuration for interface {name}")
                
                # Extract description
                desc_match = re.search(r"description (.+?)$", config_section, re.MULTILINE)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                if "shutdown" in config_section:
                    interface.status = "down"
                else:
                    interface.status = "up"
                
                logger.info(f"Adding interface {name} with status {interface.status}")
                interfaces.append(interface)
        
        return interfaces
    
    def _parse_interfaces(self, output: str, device_type: str) -> List[DeviceInterface]:
        """Parse interface information from device output."""
        interfaces = []
        
        if not output:
            return interfaces
            
        # Different parsing based on device type
        if device_type in ["cisco_ios", "cisco_nxos", "cisco_xe"]:
            # Split output by interface
            interface_sections = re.split(r"(?=\w+Ethernet\d+\/\d+|\w+GigabitEthernet\d+\/\d+|\w+Serial\d+\/\d+|Loopback\d+)", output)
            
            for section in interface_sections:
                if not section.strip():
                    continue
                    
                # Extract interface name
                name_match = re.match(r"^(\S+)", section)
                if not name_match:
                    continue
                    
                name = name_match.group(1)
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Extract IP address
                ip_match = re.search(r"Internet address is ([\d\.]+)", section)
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                
                # Extract description
                desc_match = re.search(r"Description: (.+)", section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                status_match = re.search(r"line protocol is (\w+)", section)
                if status_match:
                    interface.status = status_match.group(1)
                
                logger.info(f"Adding interface {name} with status {interface.status}")
                interfaces.append(interface)
                
        elif device_type == "juniper_junos":
            # Juniper interface pattern
            interface_pattern = r"Physical interface: (\S+), "
            interface_matches = re.finditer(interface_pattern, output)
            
            for match in interface_matches:
                name = match.group(1)
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Extract status
                status_section = output[match.end():output.find("Physical interface:", match.end())]
                if "Enabled" in status_section:
                    interface.status = "up"
                else:
                    interface.status = "down"
                    
                # Extract IP address
                ip_match = re.search(r"Local: ([\d\.]+)", status_section)
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                    
                # Extract description
                desc_match = re.search(r"Description: (.+?)\n", status_section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                    
                logger.info(f"Adding interface {name} with status {interface.status}")
                interfaces.append(interface)
                
        elif device_type == "arista_eos":
            # Arista interface pattern
            interface_sections = re.split(r"(?=\w+Ethernet\d+\/\d+|Management\d+)", output)
            
            for section in interface_sections:
                if not section.strip():
                    continue
                    
                # Extract interface name
                name_match = re.match(r"^(\S+)", section)
                if not name_match:
                    continue
                    
                name = name_match.group(1)
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Extract IP address
                ip_match = re.search(r"IP address: ([\d\.]+)", section)
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                
                # Extract description
                desc_match = re.search(r"Description: (.+?)\n", section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                status_match = re.search(r"is (\w+), line protocol is (\w+)", section)
                if status_match:
                    interface.status = status_match.group(2)  # Use line protocol status
                
                logger.info(f"Adding interface {name} with status {interface.status}")
                interfaces.append(interface)
        
        return interfaces
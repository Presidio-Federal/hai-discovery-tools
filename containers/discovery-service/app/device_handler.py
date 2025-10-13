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
            
            # Get hostname
            hostname_cmd = self._get_command("hostname", device_type)
            hostname_output = await loop.run_in_executor(None, conn.send_command, hostname_cmd)
            device_info["hostname"] = self._extract_hostname(hostname_output, device_type)
            
            # Get version information
            version_cmd = self._get_command("version", device_type)
            version_output = await loop.run_in_executor(None, conn.send_command, version_cmd)
            
            # Extract version info based on device type
            device_info["platform"] = device_type.split('_')[0] if '_' in device_type else device_type
            device_info["os_version"] = self._extract_version_info(version_output, device_type)
            device_info["model"] = self._extract_model_info(version_output, device_type)
            device_info["serial_number"] = self._extract_serial_info(version_output, device_type)
            
            # Get interface information
            interfaces_cmd = self._get_command("interfaces", device_type)
            interfaces_output = await loop.run_in_executor(None, conn.send_command, interfaces_cmd)
            device_info["interfaces"] = self._parse_interfaces(interfaces_output, device_type)
            
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
            config = await loop.run_in_executor(None, conn.send_command, config_cmd)
            
            result["raw_config"] = config
            
            # Parse configuration
            if config:
                result["parsed_config"] = ConfigParser.parse_config(config, device_type)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting config from {ip_address}: {str(e)}")
            return result
            
        finally:
            # Ensure connection is closed
            try:
                await loop.run_in_executor(None, conn.disconnect)
            except Exception:
                pass
    
    async def get_device_neighbors(self, ip_address: str, credential: Credential, 
                                 protocols: List[str], device_type: Optional[str] = None, port: int = 22) -> List[Dict[str, Any]]:
        """Get device neighbors using specified protocols."""
        neighbors = []
        
        # Connect to the device
        conn, detected_type = await self.connect_to_device(ip_address, credential, device_type, port)
        if not conn:
            return neighbors
        
        device_type = detected_type  # Use the detected type
        
        try:
            loop = asyncio.get_event_loop()
            
            # Check for CDP neighbors
            if "cdp" in protocols:
                try:
                    cdp_cmd = self._get_command("cdp_neighbors", device_type)
                    logger.info(f"Running command on {ip_address}: {cdp_cmd}")
                    cdp_output = await loop.run_in_executor(None, conn.send_command, cdp_cmd)
                    
                    if cdp_output:
                        logger.debug(f"CDP output from {ip_address}: {cdp_output[:200]}...")
                        cdp_neighbors = CDPParser.parse_cdp_output(cdp_output, device_type)
                        logger.info(f"Found {len(cdp_neighbors)} CDP neighbors on {ip_address}")
                        neighbors.extend(cdp_neighbors)
                    else:
                        logger.warning(f"No CDP output from {ip_address}")
                except Exception as e:
                    logger.error(f"Error getting CDP neighbors from {ip_address}: {str(e)}")
            
            # Check for LLDP neighbors
            if "lldp" in protocols:
                try:
                    lldp_cmd = self._get_command("lldp_neighbors", device_type)
                    logger.info(f"Running command on {ip_address}: {lldp_cmd}")
                    lldp_output = await loop.run_in_executor(None, conn.send_command, lldp_cmd)
                    
                    if lldp_output:
                        logger.debug(f"LLDP output from {ip_address}: {lldp_output[:200]}...")
                        lldp_neighbors = LLDPParser.parse_lldp_output(lldp_output, device_type)
                        logger.info(f"Found {len(lldp_neighbors)} LLDP neighbors on {ip_address}")
                        neighbors.extend(lldp_neighbors)
                    else:
                        logger.warning(f"No LLDP output from {ip_address}")
                except Exception as e:
                    logger.error(f"Error getting LLDP neighbors from {ip_address}: {str(e)}")
            
            logger.info(f"Total neighbors found for {ip_address}: {len(neighbors)}")
            return neighbors
            
        except Exception as e:
            logger.error(f"Error discovering neighbors for {ip_address}: {str(e)}")
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
            
        # For Cisco IOS/NXOS, hostname command returns just the hostname
        if device_type in ["cisco_ios", "cisco_nxos", "arista_eos"]:
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
            
        return output.strip()
    
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
    
    def _parse_interfaces(self, output: str, device_type: str) -> List[DeviceInterface]:
        """Parse interface information from device output."""
        interfaces = []
        
        if not output:
            return interfaces
            
        # Different parsing based on device type
        if device_type in ["cisco_ios", "cisco_nxos"]:
            # Split output by interface
            interface_sections = re.split(r"(?=\w+Ethernet\d+\/\d+|\w+GigabitEthernet\d+\/\d+|\w+Serial\d+\/\d+)", output)
            
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
                ip_match = re.search(r"Internet address is ([\d\.]+\/\d+)", section)
                if ip_match:
                    interface.ip_address = ip_match.group(1).split('/')[0]  # Remove CIDR notation
                
                # Extract description
                desc_match = re.search(r"Description: (.+)", section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                status_match = re.search(r"line protocol is (\w+)", section)
                if status_match:
                    interface.status = status_match.group(1)
                
                interfaces.append(interface)
                
        elif device_type == "juniper_junos":
            # Juniper interface pattern
            interface_pattern = r"Physical interface: (\S+), "
            interface_matches = re.finditer(interface_pattern, output)
            
            for match in interface_matches:
                name = match.group(1)
                
                # Create interface object
                interface = DeviceInterface(name=name)
                
                # Find the section for this interface
                start_pos = match.start()
                next_match = re.search(interface_pattern, output[start_pos + 1:])
                end_pos = start_pos + 1 + next_match.start() if next_match else len(output)
                section = output[start_pos:end_pos]
                
                # Extract IP address
                ip_match = re.search(r"Local: ([\d\.]+)", section)
                if ip_match:
                    interface.ip_address = ip_match.group(1)
                
                # Extract description
                desc_match = re.search(r"Description: (.+)", section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                status_match = re.search(r", (Physical|Administratively) (up|down)", section)
                if status_match:
                    interface.status = status_match.group(2)
                
                interfaces.append(interface)
                
        elif device_type == "arista_eos":
            # Arista interface pattern (similar to Cisco)
            interface_sections = re.split(r"(?=\w+thernet\d+\/\d+)", output)
            
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
                desc_match = re.search(r"Description: (.+)", section)
                if desc_match:
                    interface.description = desc_match.group(1).strip()
                
                # Extract status
                status_match = re.search(r"line protocol is (\w+)", section)
                if status_match:
                    interface.status = status_match.group(1)
                
                interfaces.append(interface)
        
        return interfaces
    
    def _parse_cdp_neighbors(self, output: str, device_type: str) -> List[Dict[str, Any]]:
        """Parse CDP neighbor output."""
        neighbors = []
        
        if not output:
            return neighbors
            
        # CDP parsing is similar across Cisco and Arista devices
        device_sections = re.split(r"-{4,}", output)
        
        for section in device_sections:
            if not section.strip():
                continue
                
            neighbor = {}
            
            # Extract hostname
            hostname_match = re.search(r"Device ID:[\s]*([\w\.-]+)", section)
            if hostname_match:
                neighbor["hostname"] = hostname_match.group(1)
                
            # Extract IP address
            ip_match = re.search(r"IP address:[\s]*([\d\.]+)", section)
            if ip_match:
                neighbor["ip_address"] = ip_match.group(1)
                
            # Extract platform/model
            platform_match = re.search(r"Platform:[\s]*([^,]+),", section)
            if platform_match:
                neighbor["platform"] = platform_match.group(1).strip()
                
            # Extract interface information
            local_int_match = re.search(r"Interface:[\s]*([^,]+),", section)
            remote_int_match = re.search(r"Port ID \(outgoing port\):[\s]*(.+)", section)
            
            if local_int_match:
                neighbor["local_interface"] = local_int_match.group(1).strip()
            
            if remote_int_match:
                neighbor["remote_interface"] = remote_int_match.group(1).strip()
                
            if neighbor.get("hostname") and neighbor.get("ip_address"):
                neighbors.append(neighbor)
                
        return neighbors
    
    def _parse_lldp_neighbors(self, output: str, device_type: str) -> List[Dict[str, Any]]:
        """Parse LLDP neighbor output."""
        neighbors = []
        
        if not output:
            return neighbors
            
        # Different parsing based on device type
        if device_type in ["cisco_ios", "cisco_nxos", "arista_eos"]:
            # Simple regex-based parsing for LLDP output
            device_sections = re.split(r"-{4,}|={4,}", output)
            
            for section in device_sections:
                if not section.strip():
                    continue
                    
                neighbor = {}
                
                # Extract hostname
                hostname_match = re.search(r"System Name:[\s]*([\w\.-]+)", section)
                if hostname_match:
                    neighbor["hostname"] = hostname_match.group(1)
                    
                # Extract IP address
                ip_match = re.search(r"Management Address:[\s]*([\d\.]+)", section)
                if ip_match:
                    neighbor["ip_address"] = ip_match.group(1)
                    
                # Extract platform/model
                platform_match = re.search(r"System Description:[\s]*([^\n]+)", section)
                if platform_match:
                    neighbor["platform"] = platform_match.group(1).strip()
                    
                # Extract interface information
                local_int_match = re.search(r"Local Interface:[\s]*([^\n]+)", section)
                remote_int_match = re.search(r"Port id:[\s]*([^\n]+)", section)
                
                if local_int_match:
                    neighbor["local_interface"] = local_int_match.group(1).strip()
                
                if remote_int_match:
                    neighbor["remote_interface"] = remote_int_match.group(1).strip()
                    
                if neighbor.get("hostname") and neighbor.get("ip_address"):
                    neighbors.append(neighbor)
                    
        elif device_type == "juniper_junos":
            # Parse the basic LLDP neighbor table
            lines = output.strip().split('\n')
            for line in lines:
                if "Local Interface" in line or "Parent Interface" in line or not line.strip():
                    continue
                    
                parts = line.split()
                if len(parts) >= 4:
                    neighbor = {
                        "local_interface": parts[0],
                        "remote_interface": parts[1],
                        "hostname": parts[2]
                    }
                    
                    # Try to find IP address in other parts of output
                    # This is a simplification; in a real implementation,
                    # you would need to get detailed info for each neighbor
                    neighbors.append(neighbor)
                
        return neighbors

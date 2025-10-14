"""
CDP output parser for network devices.

This module parses CDP neighbor output to extract structured information.
"""

import re
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class CDPParser:
    """Parser for CDP neighbor output."""
    
    @staticmethod
    def parse_cdp_output(output: str, device_type: str) -> List[Dict[str, Any]]:
        """
        Parse CDP neighbor output into structured data.
        
        Args:
            output: The CDP neighbor output as a string
            device_type: The type of device (cisco_ios, juniper_junos, etc.)
            
        Returns:
            A list of dictionaries containing neighbor information
        """
        if not output:
            logger.warning("No CDP output to parse")
            return []
            
        neighbors = []
        logger.info(f"Parsing CDP output for device type: {device_type}")
        
        if device_type.startswith("cisco"):
            # Split output by device sections
            device_sections = re.split(r"-{4,}", output)
            logger.info(f"Found {len(device_sections)} CDP sections to parse")
            
            for section in device_sections:
                if not section.strip():
                    continue
                    
                neighbor = {}
                
                # Extract device ID (hostname)
                hostname_match = re.search(r"Device ID:[\s]*([\w\.-]+)", section)
                if hostname_match:
                    neighbor["hostname"] = hostname_match.group(1)
                    
                # Extract IP address
                ip_match = re.search(r"IP(?:v4)? address:[\s]*([\d\.]+)", section)
                if ip_match:
                    neighbor["ip_address"] = ip_match.group(1)
                    
                # Extract platform/model
                platform_match = re.search(r"Platform:[\s]*([^,]+),", section)
                if platform_match:
                    neighbor["platform"] = platform_match.group(1).strip()
                    
                # Extract software version
                version_match = re.search(r"Version[\s:]*\n?[\s]*([\w\.\(\)]+)", section)
                if version_match:
                    neighbor["software_version"] = version_match.group(1).strip()
                    
                # Extract capabilities
                capabilities_match = re.search(r"Capabilities:[\s]*(.+?)$", section, re.MULTILINE)
                if capabilities_match:
                    capabilities = capabilities_match.group(1).strip()
                    neighbor["capabilities"] = capabilities
                    
                # Extract interface information
                local_int_match = re.search(r"Interface:[\s]*([^,]+),", section)
                remote_int_match = re.search(r"Port ID \(outgoing port\):[\s]*(.+?)$", section, re.MULTILINE)
                
                if local_int_match:
                    neighbor["local_interface"] = local_int_match.group(1).strip()
                
                if remote_int_match:
                    neighbor["remote_interface"] = remote_int_match.group(1).strip()
                    
                # Extract hold time
                holdtime_match = re.search(r"Holdtime:[\s]*(\d+) sec", section)
                if holdtime_match:
                    neighbor["holdtime"] = int(holdtime_match.group(1))
                    
                # Extract VTP Management Domain
                vtp_match = re.search(r"VTP Management Domain:[\s]*(.+?)$", section, re.MULTILINE)
                if vtp_match:
                    neighbor["vtp_domain"] = vtp_match.group(1).strip()
                    
                # Extract Native VLAN
                native_vlan_match = re.search(r"Native VLAN:[\s]*(\d+)", section)
                if native_vlan_match:
                    neighbor["native_vlan"] = native_vlan_match.group(1)
                    
                # Extract Duplex
                duplex_match = re.search(r"Duplex:[\s]*(\w+)", section)
                if duplex_match:
                    neighbor["duplex"] = duplex_match.group(1)
                    
                if neighbor.get("hostname") and neighbor.get("ip_address"):
                    logger.info(f"Adding CDP neighbor: {neighbor['hostname']} ({neighbor['ip_address']})")
                    neighbors.append(neighbor)
                    
        elif device_type == "arista_eos":
            # Arista CDP output format (similar to Cisco)
            return CDPParser.parse_cdp_output(output, "cisco_ios")
                
        logger.info(f"Parsed {len(neighbors)} CDP neighbors")
        return neighbors

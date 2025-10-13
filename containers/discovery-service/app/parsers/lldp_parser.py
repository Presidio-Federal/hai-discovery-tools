"""
LLDP output parser for network devices.

This module parses LLDP neighbor output to extract structured information.
"""

import re
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class LLDPParser:
    """Parser for LLDP neighbor output."""
    
    @staticmethod
    def parse_lldp_output(output: str, device_type: str) -> List[Dict[str, Any]]:
        """
        Parse LLDP neighbor output into structured data.
        
        Args:
            output: The LLDP neighbor output as a string
            device_type: The type of device (cisco_ios, juniper_junos, etc.)
            
        Returns:
            A list of dictionaries containing neighbor information
        """
        if not output:
            return []
            
        neighbors = []
        
        if device_type.startswith("cisco"):
            # Split output by device sections
            device_sections = re.split(r"-{4,}|={4,}", output)
            
            for section in device_sections:
                if not section.strip():
                    continue
                    
                neighbor = {}
                
                # Extract device ID (hostname)
                hostname_match = re.search(r"System Name:[\s]*([\w\.-]+)", section)
                if hostname_match:
                    neighbor["hostname"] = hostname_match.group(1)
                    
                # Extract IP address
                ip_match = re.search(r"Management Address(?:\(\w+\))?:[\s]*([\d\.]+)", section)
                if ip_match:
                    neighbor["ip_address"] = ip_match.group(1)
                    
                # Extract platform/model
                platform_match = re.search(r"System Description:[\s]*\n?[\s]*([^\n]+)", section)
                if platform_match:
                    neighbor["platform"] = platform_match.group(1).strip()
                    
                # Extract capabilities
                capabilities_match = re.search(r"System Capabilities:[\s]*(.+?)$", section, re.MULTILINE)
                if capabilities_match:
                    capabilities = capabilities_match.group(1).strip()
                    neighbor["capabilities"] = capabilities
                    
                # Extract interface information
                local_int_match = re.search(r"Local Interface:[\s]*([^\n]+)", section)
                remote_int_match = re.search(r"Port(?:\s+|\s+Description|\s+ID|\s+id):[\s]*([^\n]+)", section)
                
                if local_int_match:
                    neighbor["local_interface"] = local_int_match.group(1).strip()
                
                if remote_int_match:
                    neighbor["remote_interface"] = remote_int_match.group(1).strip()
                    
                # Extract hold time
                holdtime_match = re.search(r"Time remaining:[\s]*(\d+) seconds", section)
                if holdtime_match:
                    neighbor["holdtime"] = int(holdtime_match.group(1))
                    
                # Extract VLAN
                vlan_match = re.search(r"VLAN:[\s]*(\d+)", section)
                if vlan_match:
                    neighbor["vlan"] = vlan_match.group(1)
                    
                if neighbor.get("hostname") and neighbor.get("ip_address"):
                    neighbors.append(neighbor)
                    
        elif device_type == "juniper_junos":
            # For Juniper, parse the basic LLDP neighbor table
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
                    
        elif device_type == "arista_eos":
            # Arista LLDP output format (similar to Cisco)
            device_sections = re.split(r"-{4,}", output)
            
            for section in device_sections[1:]:  # Skip header
                if not section.strip():
                    continue
                    
                neighbor = {}
                
                # Extract local interface
                local_int_match = re.match(r"(\S+)", section)
                if local_int_match:
                    neighbor["local_interface"] = local_int_match.group(1)
                
                # Extract hostname
                hostname_match = re.search(r"System Name: \"(.+?)\"", section)
                if hostname_match:
                    neighbor["hostname"] = hostname_match.group(1)
                
                # Extract IP address
                ip_match = re.search(r"Management Address: ([\d\.]+)", section)
                if ip_match:
                    neighbor["ip_address"] = ip_match.group(1)
                
                # Extract remote interface
                remote_int_match = re.search(r"Port ID: \"(.+?)\"", section)
                if remote_int_match:
                    neighbor["remote_interface"] = remote_int_match.group(1)
                
                # Extract platform
                platform_match = re.search(r"System Description: \"(.+?)\"", section)
                if platform_match:
                    neighbor["platform"] = platform_match.group(1)
                
                if neighbor.get("hostname") and neighbor.get("ip_address"):
                    neighbors.append(neighbor)
                
        return neighbors

"""
Configuration parser for network devices.

This module parses device configurations to extract structured information.
"""

import re
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class ConfigParser:
    """Parser for network device configurations."""
    
    @staticmethod
    def parse_config(config: str, device_type: str) -> Dict[str, Any]:
        """
        Parse device configuration into structured data.
        
        Args:
            config: The device configuration as a string
            device_type: The type of device (cisco_ios, juniper_junos, etc.)
            
        Returns:
            A dictionary containing structured configuration data
        """
        if not config:
            return {}
            
        result = {
            "hostname": None,
            "interfaces": [],
            "vlans": [],
            "routing": {
                "static_routes": [],
                "ospf": {},
                "bgp": {},
                "eigrp": {}
            },
            "acls": [],
            "ntp": [],
            "snmp": {},
            "users": []
        }
        
        # Extract hostname
        result["hostname"] = ConfigParser._extract_hostname(config, device_type)
        
        # Extract interfaces
        result["interfaces"] = ConfigParser._extract_interfaces(config, device_type)
        
        # Extract VLANs
        result["vlans"] = ConfigParser._extract_vlans(config, device_type)
        
        # Extract routing information
        result["routing"] = ConfigParser._extract_routing(config, device_type)
        
        # Extract ACLs
        result["acls"] = ConfigParser._extract_acls(config, device_type)
        
        return result
    
    @staticmethod
    def _extract_hostname(config: str, device_type: str) -> Optional[str]:
        """Extract hostname from configuration."""
        if device_type.startswith("cisco"):
            match = re.search(r"^hostname\s+(\S+)", config, re.MULTILINE)
            if match:
                return match.group(1)
        elif device_type == "juniper_junos":
            match = re.search(r"set system host-name (\S+)", config)
            if match:
                return match.group(1)
        elif device_type.startswith("arista"):
            match = re.search(r"^hostname\s+(\S+)", config, re.MULTILINE)
            if match:
                return match.group(1)
                
        return None
    
    @staticmethod
    def _extract_interfaces(config: str, device_type: str) -> List[Dict[str, Any]]:
        """Extract interface information from configuration."""
        interfaces = []
        
        if device_type.startswith("cisco"):
            # Match interface blocks in Cisco configs
            interface_blocks = re.finditer(
                r"^interface\s+([^\n]+)(?:\n(?:[^\n]+))*?(?=^!|$)",
                config, re.MULTILINE
            )
            
            for block in interface_blocks:
                interface_text = block.group(0)
                name_match = re.search(r"^interface\s+([^\n]+)", interface_text)
                if not name_match:
                    continue
                    
                name = name_match.group(1)
                
                # Extract IP address
                ip_match = re.search(r"ip address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)", interface_text)
                ip_address = None
                subnet_mask = None
                if ip_match:
                    ip_address = ip_match.group(1)
                    subnet_mask = ip_match.group(2)
                
                # Extract description
                desc_match = re.search(r"description\s+(.+?)$", interface_text, re.MULTILINE)
                description = desc_match.group(1) if desc_match else None
                
                # Extract status
                shutdown = "shutdown" in interface_text
                
                # Extract VLAN info
                vlan_match = re.search(r"switchport access vlan (\d+)", interface_text)
                vlan = vlan_match.group(1) if vlan_match else None
                
                # Extract trunk info
                trunk_match = re.search(r"switchport mode trunk", interface_text)
                is_trunk = bool(trunk_match)
                
                interface = {
                    "name": name,
                    "ip_address": ip_address,
                    "subnet_mask": subnet_mask,
                    "description": description,
                    "shutdown": shutdown,
                    "vlan": vlan,
                    "is_trunk": is_trunk,
                    "raw_config": interface_text
                }
                
                interfaces.append(interface)
                
        elif device_type == "juniper_junos":
            # For Juniper, extract interface information from set commands
            interface_lines = re.finditer(r"set interfaces (\S+) .+", config)
            current_interface = None
            
            for line in interface_lines:
                interface_name = line.group(1)
                if current_interface != interface_name:
                    current_interface = interface_name
                    interface = {
                        "name": interface_name,
                        "ip_address": None,
                        "description": None,
                        "shutdown": False,
                        "raw_config": ""
                    }
                    interfaces.append(interface)
                
                # Update interface info based on the line
                line_text = line.group(0)
                
                # Extract IP address
                ip_match = re.search(r"set interfaces \S+ unit \d+ family inet address (\S+)", line_text)
                if ip_match:
                    interface["ip_address"] = ip_match.group(1)
                
                # Extract description
                desc_match = re.search(r"set interfaces \S+ description \"(.+)\"", line_text)
                if desc_match:
                    interface["description"] = desc_match.group(1)
                
                interface["raw_config"] += line_text + "\n"
                
        return interfaces
    
    @staticmethod
    def _extract_vlans(config: str, device_type: str) -> List[Dict[str, Any]]:
        """Extract VLAN information from configuration."""
        vlans = []
        
        if device_type.startswith("cisco"):
            # Match VLAN blocks in Cisco configs
            vlan_blocks = re.finditer(
                r"^vlan\s+(\d+)(?:\n(?:[^\n]+))*?(?=^!|$)",
                config, re.MULTILINE
            )
            
            for block in vlan_blocks:
                vlan_text = block.group(0)
                vlan_id_match = re.search(r"^vlan\s+(\d+)", vlan_text)
                if not vlan_id_match:
                    continue
                    
                vlan_id = vlan_id_match.group(1)
                
                # Extract name
                name_match = re.search(r"name\s+(.+?)$", vlan_text, re.MULTILINE)
                name = name_match.group(1) if name_match else None
                
                vlan = {
                    "vlan_id": vlan_id,
                    "name": name,
                    "raw_config": vlan_text
                }
                
                vlans.append(vlan)
                
        elif device_type == "juniper_junos":
            # For Juniper, extract VLAN information from set commands
            vlan_lines = re.finditer(r"set vlans (\S+) .+", config)
            current_vlan = None
            
            for line in vlan_lines:
                vlan_name = line.group(1)
                if current_vlan != vlan_name:
                    current_vlan = vlan_name
                    vlan = {
                        "name": vlan_name,
                        "vlan_id": None,
                        "raw_config": ""
                    }
                    vlans.append(vlan)
                
                # Update vlan info based on the line
                line_text = line.group(0)
                
                # Extract VLAN ID
                vlan_id_match = re.search(r"set vlans \S+ vlan-id (\d+)", line_text)
                if vlan_id_match:
                    vlan["vlan_id"] = vlan_id_match.group(1)
                
                vlan["raw_config"] += line_text + "\n"
                
        return vlans
    
    @staticmethod
    def _extract_routing(config: str, device_type: str) -> Dict[str, Any]:
        """Extract routing information from configuration."""
        routing = {
            "static_routes": [],
            "ospf": {},
            "bgp": {},
            "eigrp": {}
        }
        
        if device_type.startswith("cisco"):
            # Extract static routes
            static_routes = re.finditer(
                r"^ip route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+|\S+)",
                config, re.MULTILINE
            )
            
            for route in static_routes:
                static_route = {
                    "network": route.group(1),
                    "mask": route.group(2),
                    "next_hop": route.group(3)
                }
                routing["static_routes"].append(static_route)
            
            # Extract OSPF information
            ospf_process_match = re.search(r"^router ospf\s+(\d+)", config, re.MULTILINE)
            if ospf_process_match:
                process_id = ospf_process_match.group(1)
                routing["ospf"] = {
                    "process_id": process_id,
                    "networks": []
                }
                
                # Extract OSPF networks
                ospf_networks = re.finditer(
                    r"^network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+area\s+(\d+)",
                    config, re.MULTILINE
                )
                
                for network in ospf_networks:
                    ospf_network = {
                        "network": network.group(1),
                        "wildcard": network.group(2),
                        "area": network.group(3)
                    }
                    routing["ospf"]["networks"].append(ospf_network)
            
            # Extract BGP information
            bgp_as_match = re.search(r"^router bgp\s+(\d+)", config, re.MULTILINE)
            if bgp_as_match:
                as_number = bgp_as_match.group(1)
                routing["bgp"] = {
                    "as_number": as_number,
                    "neighbors": []
                }
                
                # Extract BGP neighbors
                bgp_neighbors = re.finditer(
                    r"^neighbor\s+(\d+\.\d+\.\d+\.\d+)\s+remote-as\s+(\d+)",
                    config, re.MULTILINE
                )
                
                for neighbor in bgp_neighbors:
                    bgp_neighbor = {
                        "ip_address": neighbor.group(1),
                        "remote_as": neighbor.group(2)
                    }
                    routing["bgp"]["neighbors"].append(bgp_neighbor)
                
        return routing
    
    @staticmethod
    def _extract_acls(config: str, device_type: str) -> List[Dict[str, Any]]:
        """Extract ACL information from configuration."""
        acls = []
        
        if device_type.startswith("cisco"):
            # Match ACL blocks in Cisco configs
            acl_lines = re.finditer(
                r"^(ip access-list \S+|access-list \d+)[\s\S]*?(?=^!|$)",
                config, re.MULTILINE
            )
            
            for acl in acl_lines:
                acl_text = acl.group(0)
                name_match = re.search(r"^(ip access-list \S+|access-list \d+)", acl_text)
                if not name_match:
                    continue
                    
                acl_name = name_match.group(1)
                
                acl_entry = {
                    "name": acl_name,
                    "raw_config": acl_text
                }
                
                acls.append(acl_entry)
                
        return acls

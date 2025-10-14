"""
Configuration exporter for network devices.

This module provides functions to export device configurations in various formats.
"""

import os
import logging
from typing import Dict, List, Any, Optional
import json

logger = logging.getLogger(__name__)


class ConfigExporter:
    """Exporter for network device configurations."""
    
    @staticmethod
    def export_raw_configs(devices: Dict[str, Any], output_dir: str) -> bool:
        """
        Export raw device configurations to text files.
        
        Args:
            devices: Dictionary of devices with their configurations
            output_dir: The directory to store configuration files
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_dir.startswith("/app/data/"):
                output_dir = f"/app/data/exports/configs"
                
            # Create directory if it doesn't exist
            try:
                os.makedirs(output_dir, exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory {output_dir}")
                # Try to use a directory we know exists
                output_dir = "/app/data/exports"
            
            # Export each device's configuration
            for ip, device in devices.items():
                if not device.get("config"):
                    continue
                    
                # Use hostname if available, otherwise use IP
                filename = device.get("hostname", ip).replace("/", "_")
                filepath = os.path.join(output_dir, f"{filename}.txt")
                
                with open(filepath, 'w') as f:
                    f.write(device["config"])
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting raw configs: {str(e)}")
            return False
    
    @staticmethod
    def export_parsed_configs(devices: Dict[str, Any], output_dir: str) -> bool:
        """
        Export parsed device configurations to JSON files.
        
        Args:
            devices: Dictionary of devices with their parsed configurations
            output_dir: The directory to store configuration files
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_dir.startswith("/app/data/"):
                output_dir = f"/app/data/exports/parsed_configs"
                
            # Create directory if it doesn't exist
            try:
                os.makedirs(output_dir, exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory {output_dir}")
                # Try to use a directory we know exists
                output_dir = "/app/data/exports"
            
            # Export each device's parsed configuration
            for ip, device in devices.items():
                if not device.get("parsed_config"):
                    continue
                    
                # Use hostname if available, otherwise use IP
                filename = device.get("hostname", ip).replace("/", "_")
                filepath = os.path.join(output_dir, f"{filename}.json")
                
                with open(filepath, 'w') as f:
                    json.dump(device["parsed_config"], f, indent=2)
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting parsed configs: {str(e)}")
            return False
    
    @staticmethod
    def export_inventory_report(devices: Dict[str, Any], output_file: str) -> bool:
        """
        Export a network inventory report in CSV format.
        
        Args:
            devices: Dictionary of devices with their information
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_file.startswith("/app/data/"):
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
                
            # Create directory if it doesn't exist
            try:
                os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory for {output_file}")
                # Try to use a directory we know exists
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
            
            # Write CSV header
            with open(output_file, 'w') as f:
                f.write("IP Address,Hostname,Platform,OS Version,Model,Serial Number,Status\n")
                
                # Write device information
                for ip, device in devices.items():
                    # Clean up hostname if it contains error message
                    hostname = device.get("hostname", "")
                    if hostname and hostname.startswith("^"):
                        hostname = ""
                        
                    # Get device information from various sources
                    platform = device.get("platform", "")
                    os_version = device.get("os_version", "")
                    
                    # Try to get model from device_info or parsed_config
                    model = device.get("model", "")
                    if not model and "parsed_config" in device:
                        # Try to extract model from parsed config
                        parsed_config = device.get("parsed_config", {})
                        if isinstance(parsed_config, dict):
                            # Check inventory section if it exists
                            if "inventory" in parsed_config and isinstance(parsed_config["inventory"], list):
                                for item in parsed_config["inventory"]:
                                    if item.get("name", "").lower() == "chassis":
                                        model = item.get("pid", "")
                                        break
                    
                    # Try to get serial number from device_info or parsed_config
                    serial = device.get("serial_number", "")
                    if not serial and "parsed_config" in device:
                        # Try to extract serial from parsed config
                        parsed_config = device.get("parsed_config", {})
                        if isinstance(parsed_config, dict):
                            # Check inventory section if it exists
                            if "inventory" in parsed_config and isinstance(parsed_config["inventory"], list):
                                for item in parsed_config["inventory"]:
                                    if item.get("name", "").lower() == "chassis":
                                        serial = item.get("sn", "")
                                        break
                    
                    status = device.get("discovery_status", "")
                    
                    # Escape any commas in fields
                    hostname = hostname.replace(",", "_")
                    platform = platform.replace(",", "_")
                    os_version = os_version.replace(",", "_")
                    model = model.replace(",", "_")
                    serial = serial.replace(",", "_")
                    
                    f.write(f"{ip},{hostname},{platform},{os_version},{model},{serial},{status}\n")
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting inventory report: {str(e)}")
            return False
    
    @staticmethod
    def export_interface_report(devices: Dict[str, Any], output_file: str) -> bool:
        """
        Export a network interface report in CSV format.
        
        Args:
            devices: Dictionary of devices with their interface information
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_file.startswith("/app/data/"):
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
                
            # Create directory if it doesn't exist
            try:
                os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory for {output_file}")
                # Try to use a directory we know exists
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
            
            # Write CSV header
            with open(output_file, 'w') as f:
                f.write("Device IP,Hostname,Interface Name,IP Address,Description,Status,VLAN,Connected To\n")
                
                # Write interface information
                for ip, device in devices.items():
                    # Clean up hostname if it contains error message
                    hostname = device.get("hostname", "")
                    if hostname and hostname.startswith("^"):
                        hostname = ""
                    
                    # Try to get interfaces from device or from parsed_config
                    interfaces = device.get("interfaces", [])
                    
                    # If no interfaces found, try to extract from parsed_config
                    if not interfaces and "parsed_config" in device:
                        parsed_config = device.get("parsed_config", {})
                        if isinstance(parsed_config, dict) and "interfaces" in parsed_config:
                            parsed_interfaces = parsed_config.get("interfaces", [])
                            if isinstance(parsed_interfaces, list):
                                # Convert parsed interfaces to the expected format
                                for intf in parsed_interfaces:
                                    interfaces.append({
                                        "name": intf.get("name", ""),
                                        "ip_address": intf.get("ip_address", ""),
                                        "description": intf.get("description", ""),
                                        "status": "up" if not intf.get("shutdown", True) else "down",
                                        "vlan": intf.get("vlan", ""),
                                    })
                    
                    # Add connection information from neighbors
                    neighbor_connections = {}
                    for neighbor in device.get("neighbors", []):
                        local_intf = neighbor.get("local_interface", "")
                        remote_host = neighbor.get("hostname", "")
                        remote_intf = neighbor.get("remote_interface", "")
                        if local_intf and remote_host:
                            neighbor_connections[local_intf] = f"{remote_host} ({remote_intf})"
                    
                    # Write each interface
                    for interface in interfaces:
                        name = interface.get("name", "")
                        intf_ip = interface.get("ip_address", "")
                        description = interface.get("description", "").replace(",", " ")
                        status = interface.get("status", "")
                        vlan = interface.get("vlan", "")
                        
                        # Get connected_to from neighbor connections
                        connected_to = neighbor_connections.get(name, interface.get("connected_to", ""))
                        
                        f.write(f"{ip},{hostname},{name},{intf_ip},{description},{status},{vlan},{connected_to}\n")
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting interface report: {str(e)}")
            return False

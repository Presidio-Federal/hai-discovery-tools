"""
Configuration exporter for network devices.

This module provides functions to export device configurations in various formats.
"""

import os
import logging
from typing import Dict, List, Any, Optional
import json
from datetime import datetime, date

logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects and Pydantic models
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        # Handle Pydantic models
        if hasattr(obj, 'dict') and callable(obj.dict):
            return obj.dict()
        # Handle other custom objects
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


class ConfigExporter:
    """Exporter for network device configurations."""
    
    @classmethod
    def _get_value(obj, key, default=None):
        """
        Safely extract a value from an object or dictionary.
        
        Args:
            obj: Object or dictionary to extract value from
            key: Key or attribute name
            default: Default value if key/attribute doesn't exist
            
        Returns:
            The value or default
        """
        if hasattr(obj, 'dict') and callable(obj.dict):
            # It's a Pydantic model
            return getattr(obj, key, default)
        elif hasattr(obj, 'get'):
            # It's a dictionary
            return obj.get(key, default)
        elif hasattr(obj, key):
            # It's an object with the attribute
            return getattr(obj, key, default)
        else:
            # Default case
            return default
    
    @classmethod
    def export_raw_configs(cls, devices: Dict[str, Any], output_dir: str) -> bool:
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
                # Skip devices without config
                config = self._get_value(device, "config")
                if not config:
                    continue
                
                # Use hostname if available, otherwise use IP
                hostname = self._get_value(device, "hostname", ip)
                filename = str(hostname).replace("/", "_")
                filepath = os.path.join(output_dir, f"{filename}.txt")
                
                with open(filepath, 'w') as f:
                    f.write(config)
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting raw configs: {str(e)}")
            return False
    
    @classmethod
    def export_parsed_configs(cls, devices: Dict[str, Any], output_dir: str) -> bool:
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
                # Skip devices without parsed config
                parsed_config = self._get_value(device, "parsed_config")
                if not parsed_config:
                    continue
                
                # Use hostname if available, otherwise use IP
                hostname = self._get_value(device, "hostname", ip)
                filename = str(hostname).replace("/", "_")
                filepath = os.path.join(output_dir, f"{filename}.json")
                
                with open(filepath, 'w') as f:
                    json.dump(parsed_config, f, indent=2, cls=DateTimeEncoder)
                    
            return True
            
        except Exception as e:
            logger.error(f"Error exporting parsed configs: {str(e)}")
            return False
    
    @classmethod
    def export_inventory_json(cls, devices: Dict[str, Any], output_file: str) -> bool:
        """
        Export a network inventory report in JSON format.
        
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
            
            # Log what we're working with
            logger.info(f"Exporting inventory for {len(devices)} devices to {output_file}")
            
            # Prepare device inventory data
            inventory_data = []
            
            for ip, device in devices.items():
                # Log the device we're processing
                logger.info(f"Processing device {ip} for inventory export")
                
                # Clean up hostname if it contains error message
                hostname = cls._get_value(device, "hostname", "")
                if hostname and (str(hostname).startswith("^") or "Invalid input" in str(hostname)):
                    # Try to get hostname from parsed_config
                    parsed_config = cls._get_value(device, "parsed_config", {})
                    if isinstance(parsed_config, dict) and "hostname" in parsed_config:
                        hostname = parsed_config["hostname"]
                    else:
                        hostname = ""
                    
                # Get device information from various sources
                platform = cls._get_value(device, "platform", "")
                os_version = cls._get_value(device, "os_version", "")
                
                # Try to get model from device_info or parsed_config
                model = cls._get_value(device, "model", "")
                if not model:
                    # Try to extract model from parsed config
                    parsed_config = cls._get_value(device, "parsed_config", {})
                    if isinstance(parsed_config, dict):
                        # Check inventory section if it exists
                        if "inventory" in parsed_config and isinstance(parsed_config["inventory"], list):
                            for item in parsed_config["inventory"]:
                                if item.get("name", "").lower() == "chassis":
                                    model = item.get("pid", "")
                                    break
                
                # If still no model, try to extract from config
                if not model:
                    config = cls._get_value(device, "config", "")
                    if config:
                        # Look for hardware info in config
                        if "C8000V" in config:
                            model = "C8000V"
                        elif "CSR1000V" in config:
                            model = "CSR1000V"
                
                # Try to get serial number from device_info or parsed_config
                serial = cls._get_value(device, "serial_number", "")
                if not serial:
                    # Try to extract serial from parsed config
                    parsed_config = cls._get_value(device, "parsed_config", {})
                    if isinstance(parsed_config, dict):
                        # Check inventory section if it exists
                        if "inventory" in parsed_config and isinstance(parsed_config["inventory"], list):
                            for item in parsed_config["inventory"]:
                                if item.get("name", "").lower() == "chassis":
                                    serial = item.get("sn", "")
                                    break
                
                # If still no serial, try to extract from config
                if not serial:
                    config = cls._get_value(device, "config", "")
                    if config:
                        # Look for serial in config
                        import re
                        serial_match = re.search(r'license udi pid \S+ sn (\S+)', config)
                        if serial_match:
                            serial = serial_match.group(1)
                
                status = cls._get_value(device, "discovery_status", "")
                
                # Create device entry
                device_entry = {
                    "ip_address": ip,
                    "hostname": hostname,
                    "platform": platform,
                    "os_version": os_version,
                    "model": model,
                    "serial_number": serial,
                    "status": status
                }
                
                # Log the entry we're adding
                logger.info(f"Adding device to inventory: {hostname} ({ip})")
                
                inventory_data.append(device_entry)
            
            # Write JSON data
            with open(output_file, 'w') as f:
                json.dump({"devices": inventory_data}, f, indent=2, cls=DateTimeEncoder)
                
            logger.info(f"Successfully exported {len(inventory_data)} devices to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting inventory JSON: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    @classmethod
    def export_inventory_report(cls, devices: Dict[str, Any], output_file: str) -> bool:
        """
        DEPRECATED: Use export_inventory_json instead.
        This method is kept for backward compatibility but redirects to export_inventory_json.
        
        Args:
            devices: Dictionary of devices with their information
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        # Redirect to the JSON export method
        # Convert the output file path to .json extension
        json_output_file = output_file
        if output_file.endswith('.csv'):
            json_output_file = output_file.replace('.csv', '.json')
        
        logger.warning(f"export_inventory_report is deprecated. Redirecting to export_inventory_json with file: {json_output_file}")
        return cls.export_inventory_json(devices, json_output_file)
    
    @classmethod
    def export_interface_json(cls, devices: Dict[str, Any], output_file: str) -> bool:
        """
        Export a network interface report in JSON format.
        
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
            
            # Prepare interface inventory data
            interface_data = []
            
            # Process each device
            for ip, device in devices.items():
                # Get hostname
                hostname = cls._get_value(device, "hostname", "")
                if not hostname:
                    hostname = ip
                
                # Try to get interfaces from the device
                interfaces = []
                
                # Check different ways interfaces might be stored
                device_interfaces = cls._get_value(device, "interfaces", [])
                
                # Log what we found for debugging
                logger.debug(f"Device {ip}: Found {len(device_interfaces)} interfaces")
                
                # Process each interface
                for intf in device_interfaces:
                    # Handle both dictionary and object interfaces
                    if hasattr(intf, 'dict') and callable(intf.dict):
                        # It's a Pydantic model
                        interface_entry = intf.dict()
                    elif isinstance(intf, dict):
                        # It's already a dictionary
                        interface_entry = intf
                    else:
                        # Try to convert to dict
                        try:
                            interface_entry = intf.__dict__
                        except:
                            logger.warning(f"Could not convert interface to dict: {intf}")
                            continue
                    
                    # Add device information
                    interface_entry["device_ip"] = ip
                    interface_entry["device_hostname"] = hostname
                    
                    # Add to the list
                    interface_data.append(interface_entry)
            
            # Write JSON data
            with open(output_file, 'w') as f:
                json.dump({"interfaces": interface_data}, f, indent=2, cls=DateTimeEncoder)
                
            return True
            
        except Exception as e:
            logger.error(f"Error exporting interface JSON: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    @classmethod
    def export_interface_report(cls, devices: Dict[str, Any], output_file: str) -> bool:
        """
        DEPRECATED: Use export_interface_json instead.
        This method is kept for backward compatibility but redirects to export_interface_json.
        
        Args:
            devices: Dictionary of devices with their interface information
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        # Redirect to the JSON export method
        # Convert the output file path to .json extension
        json_output_file = output_file
        if output_file.endswith('.csv'):
            json_output_file = output_file.replace('.csv', '.json')
        
        logger.warning(f"export_interface_report is deprecated. Redirecting to export_interface_json with file: {json_output_file}")
        return cls.export_interface_json(devices, json_output_file)

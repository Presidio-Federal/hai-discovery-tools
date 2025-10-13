"""
Nornir-based discovery method implementation.

This method uses the Nornir automation framework to discover and gather
information from network devices in parallel.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
import tempfile

from nornir import InitNornir
from nornir.core.task import Task, Result
from nornir_netmiko.tasks import netmiko_send_command
from nornir_napalm.plugins.tasks import napalm_get
import yaml

from .base import DiscoveryMethodBase
from ..models import DiscoveryConfig, DiscoveryResult, Device, Credential

logger = logging.getLogger(__name__)


class NornirDiscovery(DiscoveryMethodBase):
    """Nornir-based network discovery method."""
    
    @property
    def name(self) -> str:
        """Get the name of this discovery method."""
        return "nornir_discovery"
    
    @property
    def description(self) -> str:
        """Get the description of this discovery method."""
        return "Discovers network devices using the Nornir automation framework"
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize Nornir discovery with configuration."""
        super().__init__(config)
        self.discovered_ips: Set[str] = set()
        self.pending_ips: Set[str] = set(config.seed_devices)
    
    async def run(self) -> DiscoveryResult:
        """Run Nornir discovery process."""
        self.result.start_time = datetime.now()
        
        try:
            # Initialize Nornir with seed devices
            nr = self._initialize_nornir()
            
            if not nr:
                logger.error("Failed to initialize Nornir")
                return self.result
            
            # Run discovery tasks
            results = nr.run(
                task=self._gather_device_info
            )
            
            # Process results
            for host_name, host_result in results.items():
                if host_result.failed:
                    logger.error(f"Failed to gather info from {host_name}: {host_result.exception}")
                    continue
                
                # Get the IP address
                ip_address = nr.inventory.hosts[host_name].hostname
                
                # Create device object
                device = Device(ip_address=ip_address)
                
                # Extract device info from results
                if "facts" in host_result[0].result:
                    facts = host_result[0].result["facts"]
                    device.hostname = facts.get("hostname")
                    device.os_version = facts.get("os_version")
                    device.model = facts.get("model")
                    device.serial_number = facts.get("serial_number")
                    device.vendor = facts.get("vendor")
                
                # Extract config
                if "config" in host_result[1].result:
                    device.config = host_result[1].result["config"]["running"]
                
                # Extract interfaces
                if "interfaces" in host_result[2].result:
                    interfaces_data = host_result[2].result["interfaces"]
                    for name, data in interfaces_data.items():
                        interface = {
                            "name": name,
                            "description": data.get("description"),
                            "ip_address": next(iter(data.get("ipv4", {}).keys()), None),
                            "status": "up" if data.get("is_up") else "down"
                        }
                        device.interfaces.append(interface)
                
                # Extract neighbors
                if len(host_result) > 3 and "result" in host_result[3]:
                    neighbors_data = host_result[3].result
                    neighbors = self._parse_neighbors(neighbors_data)
                    device.neighbors = neighbors
                    
                    # Add new neighbors to pending list
                    for neighbor in neighbors:
                        if "ip_address" in neighbor and neighbor["ip_address"]:
                            neighbor_ip = neighbor["ip_address"]
                            if (neighbor_ip not in self.discovered_ips and 
                                not self._is_excluded(neighbor_ip)):
                                self.pending_ips.add(neighbor_ip)
                
                # Mark as successfully discovered
                device.discovery_status = "discovered"
                device.last_seen = datetime.now()
                
                # Add to result
                self.result.devices[ip_address] = device
                self.discovered_ips.add(ip_address)
            
            # Process additional depths if needed
            current_depth = 1
            while current_depth < self.config.max_depth and self.pending_ips:
                # Get the current batch of IPs to process
                current_batch = self.pending_ips.copy()
                self.pending_ips = set()
                
                # Initialize Nornir for this batch
                nr = self._initialize_nornir(current_batch)
                if not nr:
                    break
                
                # Run discovery tasks
                results = nr.run(
                    task=self._gather_device_info
                )
                
                # Process results (same as above)
                for host_name, host_result in results.items():
                    if host_result.failed:
                        logger.error(f"Failed to gather info from {host_name}: {host_result.exception}")
                        continue
                    
                    # Get the IP address
                    ip_address = nr.inventory.hosts[host_name].hostname
                    
                    # Skip if already discovered
                    if ip_address in self.discovered_ips:
                        continue
                    
                    # Create device object
                    device = Device(ip_address=ip_address)
                    
                    # Extract device info from results (same as above)
                    if "facts" in host_result[0].result:
                        facts = host_result[0].result["facts"]
                        device.hostname = facts.get("hostname")
                        device.os_version = facts.get("os_version")
                        device.model = facts.get("model")
                        device.serial_number = facts.get("serial_number")
                        device.vendor = facts.get("vendor")
                    
                    # Extract config
                    if "config" in host_result[1].result:
                        device.config = host_result[1].result["config"]["running"]
                    
                    # Extract interfaces
                    if "interfaces" in host_result[2].result:
                        interfaces_data = host_result[2].result["interfaces"]
                        for name, data in interfaces_data.items():
                            interface = {
                                "name": name,
                                "description": data.get("description"),
                                "ip_address": next(iter(data.get("ipv4", {}).keys()), None),
                                "status": "up" if data.get("is_up") else "down"
                            }
                            device.interfaces.append(interface)
                    
                    # Extract neighbors
                    if len(host_result) > 3 and "result" in host_result[3]:
                        neighbors_data = host_result[3].result
                        neighbors = self._parse_neighbors(neighbors_data)
                        device.neighbors = neighbors
                        
                        # Add new neighbors to pending list
                        for neighbor in neighbors:
                            if "ip_address" in neighbor and neighbor["ip_address"]:
                                neighbor_ip = neighbor["ip_address"]
                                if (neighbor_ip not in self.discovered_ips and 
                                    not self._is_excluded(neighbor_ip)):
                                    self.pending_ips.add(neighbor_ip)
                    
                    # Mark as successfully discovered
                    device.discovery_status = "discovered"
                    device.last_seen = datetime.now()
                    
                    # Add to result
                    self.result.devices[ip_address] = device
                    self.discovered_ips.add(ip_address)
                
                # Increment depth counter
                current_depth += 1
            
            # Update final statistics
            self.result.total_devices_found = len(self.result.devices)
            self.result.successful_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status == "discovered"
            )
            self.result.failed_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status in ["failed", "unreachable"]
            )
            
            # Build topology map
            self._build_topology()
            
        except Exception as e:
            logger.error(f"Discovery process error: {str(e)}")
            
        finally:
            self.result.end_time = datetime.now()
            return self.result
    
    def _initialize_nornir(self, hosts: Optional[Set[str]] = None) -> Any:
        """Initialize Nornir with the specified hosts."""
        try:
            # Create a temporary inventory file
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False) as hosts_file:
                hosts_data = {}
                
                # Use provided hosts or seed devices
                target_hosts = hosts if hosts is not None else self.config.seed_devices
                
                # Create host entries
                for i, ip in enumerate(target_hosts):
                    host_name = f"host{i}"
                    hosts_data[host_name] = {
                        "hostname": ip,
                        "platform": "ios",  # Default platform, will be auto-detected
                    }
                
                # Write hosts to file
                yaml.dump({"hosts": hosts_data}, hosts_file)
                hosts_file_path = hosts_file.name
            
            # Create a temporary group file with credentials
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False) as groups_file:
                groups_data = {
                    "defaults": {
                        "username": self.config.credentials[0]["username"],
                        "password": self.config.credentials[0]["password"],
                        "connection_options": {
                            "netmiko": {
                                "extras": {
                                    "timeout": self.config.timeout
                                }
                            },
                            "napalm": {
                                "extras": {
                                    "timeout": self.config.timeout
                                }
                            }
                        }
                    }
                }
                
                # Add enable secret if provided
                if "enable_secret" in self.config.credentials[0]:
                    groups_data["defaults"]["connection_options"]["netmiko"]["extras"]["secret"] = self.config.credentials[0]["enable_secret"]
                
                # Write groups to file
                yaml.dump({"groups": groups_data}, groups_file)
                groups_file_path = groups_file.name
            
            # Initialize Nornir
            nr = InitNornir(
                inventory={
                    "plugin": "YAMLInventory",
                    "options": {
                        "host_file": hosts_file_path,
                        "group_file": groups_file_path,
                    }
                },
                runner={
                    "plugin": "threaded",
                    "options": {
                        "num_workers": self.config.concurrent_connections
                    }
                }
            )
            
            # Clean up temporary files
            os.unlink(hosts_file_path)
            os.unlink(groups_file_path)
            
            return nr
            
        except Exception as e:
            logger.error(f"Error initializing Nornir: {str(e)}")
            return None
    
    def _gather_device_info(self, task: Task) -> Result:
        """Gather device information using Nornir tasks."""
        # Get device facts
        facts_result = task.run(
            task=napalm_get,
            getters=["facts"]
        )
        
        # Get device configuration
        config_result = task.run(
            task=napalm_get,
            getters=["config"]
        )
        
        # Get interfaces
        interfaces_result = task.run(
            task=napalm_get,
            getters=["interfaces"]
        )
        
        # Get neighbors (CDP/LLDP)
        if "cdp" in self.config.discovery_protocols:
            neighbors_result = task.run(
                task=netmiko_send_command,
                command_string="show cdp neighbors detail"
            )
        elif "lldp" in self.config.discovery_protocols:
            neighbors_result = task.run(
                task=netmiko_send_command,
                command_string="show lldp neighbors detail"
            )
        
        return Result(
            host=task.host,
            result="Device information gathered successfully"
        )
    
    def _parse_neighbors(self, neighbors_data: str) -> List[Dict[str, Any]]:
        """Parse neighbor information from command output."""
        neighbors = []
        
        # This is a simplified parsing, in a real implementation
        # you would use TextFSM templates or more sophisticated parsing
        
        # Simple CDP parsing
        if "Device ID" in neighbors_data:
            sections = neighbors_data.split("-------------------------")
            for section in sections:
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
        
        # Simple LLDP parsing
        elif "System Name" in neighbors_data:
            sections = neighbors_data.split("-------------------------")
            for section in sections:
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
        
        return neighbors
    
    def _is_excluded(self, ip_address: str) -> bool:
        """Check if an IP address matches exclusion patterns."""
        import re
        for pattern in self.config.exclude_patterns:
            if re.match(pattern, ip_address):
                return True
        return False
    
    def _build_topology(self) -> None:
        """Build network topology map from discovered devices."""
        topology = {}
        
        # Create topology map
        for ip, device in self.result.devices.items():
            if device.discovery_status != "discovered":
                continue
                
            # Initialize empty adjacency list
            topology[ip] = []
            
            # Add neighbors
            for neighbor in device.neighbors:
                if "ip_address" in neighbor and neighbor["ip_address"] in self.result.devices:
                    topology[ip].append(neighbor["ip_address"])
        
        self.result.topology = topology

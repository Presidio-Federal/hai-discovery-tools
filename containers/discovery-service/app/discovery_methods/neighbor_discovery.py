"""
Neighbor-based network discovery.

This module implements network discovery using CDP/LLDP neighbor information.
"""

import logging
import asyncio
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime

from app.models import DiscoveryConfig, DiscoveryResult, Device, Credential
from app.discovery_methods.base import DiscoveryMethodBase
from app.device_handler import DeviceHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NeighborDiscovery(DiscoveryMethodBase):
    """
    Discovery method that uses CDP/LLDP neighbor information to
    discover network devices.
    """
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize with discovery configuration."""
        super().__init__(config)
        self.device_handler = DeviceHandler()
        self.visited_ips = set()
        self.queue = asyncio.Queue()
        self.semaphore = None  # Will be initialized in run()
        self.hostname_to_ips = {}  # Map hostnames to IPs for deduplication
        self.ip_to_hostname = {}  # Map IPs to hostnames for deduplication
        self.unique_devices = {}  # Store unique devices by hostname
        
    @property
    def name(self) -> str:
        """Return the name of the discovery method."""
        return "neighbor_discovery"
    
    @property
    def description(self) -> str:
        """Return a description of the discovery method."""
        return "Discovers network devices using CDP/LLDP neighbor information"
    
    async def run(self) -> DiscoveryResult:
        """Run the discovery process."""
        logger.info("Starting neighbor-based discovery")
        
        self.result.start_time = datetime.now()
        self.result.status = "running"
        
        # Initialize semaphore for limiting concurrent connections
        self.semaphore = asyncio.Semaphore(self.config.concurrent_connections)
        
        try:
            # Add seed devices to the queue
            for seed_device in self.config.seed_devices:
                ip_address, port = self.config.parse_seed_device(seed_device)
                logger.info(f"Adding seed device to queue: {ip_address}:{port}")
                await self.queue.put((ip_address, port, 0))  # (ip, port, depth)
            
            # Process queue until empty or max depth reached
            tasks = []
            for _ in range(min(self.config.concurrent_connections, len(self.config.seed_devices))):
                task = asyncio.create_task(self._worker())
                tasks.append(task)
                
            # Wait for all workers to complete with an overall timeout
            try:
                # Set an overall timeout for the entire discovery process
                overall_timeout = max(self.config.timeout * 3, 180)  # At least 3 minutes
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=overall_timeout)
            except asyncio.TimeoutError:
                logger.error(f"Discovery process timed out after {overall_timeout} seconds")
                # Cancel any remaining tasks
                for task in tasks:
                    if not task.done():
                        task.cancel()
            
            # Build topology map
            self._build_topology()
            
            # Update result status
            self.result.status = "completed"
            self.result.end_time = datetime.now()
            self.result.total_devices_found = len(self.result.devices)
            self.result.successful_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status == "discovered"
            )
            self.result.failed_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status in ["failed", "unreachable"]
            )
            
            logger.info(f"Discovery completed: {self.result.total_devices_found} devices found, "
                      f"{self.result.successful_connections} successful, "
                      f"{self.result.failed_connections} failed")
            
            return self.result
            
        except Exception as e:
            logger.error(f"Error during discovery: {str(e)}")
            self.result.status = "failed"
            self.result.end_time = datetime.now()
            return self.result
    
    async def _worker(self) -> None:
        """Worker that processes devices from the queue."""
        while not self.queue.empty():
            try:
                # Get next device from queue
                ip_address, port, depth = await self.queue.get()
                
                # Skip if we've already visited this IP or reached max depth
                if ip_address in self.visited_ips or depth > self.config.max_depth:
                    self.queue.task_done()
                    continue
                    
                # Check if this IP belongs to a device we've already discovered
                if ip_address in self.ip_to_hostname:
                    hostname = self.ip_to_hostname[ip_address]
                    logger.info(f"Skipping {ip_address} as it belongs to already discovered device {hostname}")
                    
                    # Add this IP to the existing device's record
                    if hostname in self.unique_devices:
                        self.unique_devices[hostname]["ip_addresses"].append(ip_address)
                        logger.info(f"Added {ip_address} to existing device {hostname}")
                    
                    self.queue.task_done()
                    continue
                
                # Mark as visited
                self.visited_ips.add(ip_address)
                
                # Process device with timeout
                try:
                    # Set a timeout for processing each device
                    await asyncio.wait_for(
                        self.process_device(ip_address, port, depth),
                        timeout=self.config.timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Processing device {ip_address}:{port} timed out after {self.config.timeout} seconds")
                    # Create a failed device entry if it doesn't exist
                    if ip_address not in self.result.devices:
                        device = Device(ip_address=ip_address)
                        device.discovery_status = "failed"
                        device.discovery_error = f"Processing timed out after {self.config.timeout} seconds"
                        self.result.devices[ip_address] = device
                except Exception as e:
                    logger.error(f"Error processing device {ip_address}:{port}: {str(e)}")
                    # Create a failed device entry if it doesn't exist
                    if ip_address not in self.result.devices:
                        device = Device(ip_address=ip_address)
                        device.discovery_status = "failed"
                        device.discovery_error = str(e)
                        self.result.devices[ip_address] = device
                
                # Mark task as done
                self.queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker error: {str(e)}")
                continue
    
    async def process_device(self, ip_address: str, port: int, depth: int) -> None:
        """Process a single device."""
        logger.info(f"Processing device {ip_address}:{port} at depth {depth}")
        
        # Skip if device should be excluded
        if self._should_exclude(ip_address):
            logger.info(f"Skipping excluded device: {ip_address}")
            return
        
        # Create device entry if it doesn't exist
        if ip_address not in self.result.devices:
            device = Device(ip_address=ip_address)
            self.result.devices[ip_address] = device
        else:
            device = self.result.devices[ip_address]
        
        # Try each credential until successful
        for credential_dict in self.config.credentials:
            credential = credential_dict.copy()
            credential["port"] = port  # Add port to credential
            
            try:
                # Detect device type
                logger.info(f"Detecting device type for {ip_address}:{port}")
                # Convert credential dict to Credential object
                cred_obj = Credential(**credential)
                device_type = await self.device_handler.detect_device_type(
                    ip_address, cred_obj, port
                )
                
                if not device_type:
                    logger.warning(f"Could not detect device type for {ip_address}:{port}")
                    continue
                
                logger.info(f"Detected device type: {device_type} for {ip_address}:{port}")
                device.device_type = device_type
                
                # Get device information
                logger.info(f"Getting device information for {ip_address}:{port}")
                device_info = await self.device_handler.get_device_info(
                    ip_address, cred_obj, device_type, port
                )
                
                if device_info:
                    # Update device with information
                    for key, value in device_info.items():
                        if hasattr(device, key) and value is not None:
                            setattr(device, key, value)
                            
                    # Ensure interfaces are properly set
                    if "interfaces" in device_info and device_info["interfaces"]:
                        logger.info(f"Found {len(device_info['interfaces'])} interfaces for {ip_address}")
                        try:
                            device.interfaces = [intf.dict() for intf in device_info["interfaces"]]
                            logger.info(f"Successfully set {len(device.interfaces)} interfaces for {ip_address}")
                        except Exception as e:
                            logger.error(f"Error converting interfaces to dict: {str(e)}")
                            # Try direct assignment as fallback
                            device.interfaces = device_info["interfaces"]
                    
                    # Update status
                    device.discovery_status = "discovered"
                    device.credentials_used = {
                        "username": credential["username"],
                        "auth_type": credential.get("auth_type", "password"),
                        "port": str(port)  # Convert port to string to avoid serialization issues
                    }
                    
                    # Handle device deduplication based on hostname
                    if device.hostname and device.hostname not in ["", None]:
                        # Clean up any error messages in hostname
                        if device.hostname.startswith("^") or "Invalid input" in device.hostname:
                            # Try to get hostname from parsed_config
                            if device.parsed_config and "hostname" in device.parsed_config:
                                device.hostname = device.parsed_config["hostname"]
                        
                        # If we have a valid hostname, track it for deduplication
                        if device.hostname and not device.hostname.startswith("^") and "Invalid input" not in device.hostname:
                            logger.info(f"Tracking device {device.hostname} with IP {ip_address} for deduplication")
                            
                            # Add this IP to the hostname's IP list
                            if device.hostname not in self.hostname_to_ips:
                                self.hostname_to_ips[device.hostname] = []
                            self.hostname_to_ips[device.hostname].append(ip_address)
                            
                            # Map this IP to the hostname
                            self.ip_to_hostname[ip_address] = device.hostname
                            
                            # Initialize the all_ip_addresses list if it doesn't exist
                            if not hasattr(device, 'all_ip_addresses') or not device.all_ip_addresses:
                                device.all_ip_addresses = [ip_address]
                            elif ip_address not in device.all_ip_addresses:
                                device.all_ip_addresses.append(ip_address)
                                
                            # Check if this device has other interfaces with IP addresses
                            if device.interfaces:
                                for intf in device.interfaces:
                                    if isinstance(intf, dict) and intf.get("ip_address"):
                                        intf_ip = intf.get("ip_address")
                                        # Skip DHCP interfaces
                                        if intf_ip and intf_ip != "dhcp" and intf_ip not in self.ip_to_hostname:
                                            logger.info(f"Mapping interface IP {intf_ip} to device {device.hostname}")
                                            self.ip_to_hostname[intf_ip] = device.hostname
                                            
                                            # Add to the device's all_ip_addresses list
                                            if intf_ip not in device.all_ip_addresses:
                                                device.all_ip_addresses.append(intf_ip)
                                                
                                        # Also check for secondary IPs
                                        if isinstance(intf, dict) and intf.get("secondary_ips"):
                                            for sec_ip in intf.get("secondary_ips", []):
                                                if isinstance(sec_ip, dict) and sec_ip.get("ip"):
                                                    sec_ip_addr = sec_ip.get("ip")
                                                    if sec_ip_addr and sec_ip_addr not in self.ip_to_hostname:
                                                        logger.info(f"Mapping secondary IP {sec_ip_addr} to device {device.hostname}")
                                                        self.ip_to_hostname[sec_ip_addr] = device.hostname
                                                        
                                                        # Add to the device's all_ip_addresses list
                                                        if sec_ip_addr not in device.all_ip_addresses:
                                                            device.all_ip_addresses.append(sec_ip_addr)
                    
                    # Extract device configuration
                    logger.info(f"Extracting configuration from {ip_address}:{port}")
                    config_result = await self.device_handler.get_device_config(
                        ip_address, cred_obj, device_type, port
                    )
                    device.config = config_result.get("raw_config")
                    device.parsed_config = config_result.get("parsed_config")
                    
                    # Discover neighbors
                    logger.info(f"Discovering neighbors for {ip_address}:{port} using {', '.join(self.config.discovery_protocols)}")
                    neighbors = await self.device_handler.get_device_neighbors(
                        ip_address, cred_obj, self.config.discovery_protocols, device_type, port
                    )
                    
                    if neighbors:
                        logger.info(f"Found {len(neighbors)} neighbors for {ip_address}:{port}")
                        device.neighbors = neighbors
                        
                        # Add neighbors to queue if within depth limit
                        if depth < self.config.max_depth:
                            for neighbor in neighbors:
                                if "ip_address" in neighbor:
                                    neighbor_ip = neighbor["ip_address"]
                                    
                                    # Skip if we've already visited this IP or it should be excluded
                                    if neighbor_ip in self.visited_ips or self._should_exclude(neighbor_ip):
                                        continue
                                        
                                    # Skip if this IP belongs to a device we've already discovered
                                    if neighbor_ip in self.ip_to_hostname:
                                        logger.info(f"Skipping neighbor {neighbor_ip} as it belongs to already discovered device {self.ip_to_hostname[neighbor_ip]}")
                                        continue
                                    
                                    logger.info(f"Adding neighbor {neighbor_ip} to queue at depth {depth + 1}")
                                    await self.queue.put((neighbor_ip, 22, depth + 1))  # Default to port 22 for neighbors
                    
                    # Successfully processed device, break credential loop
                    break
                    
            except Exception as e:
                logger.error(f"Error processing device {ip_address}:{port}: {str(e)}")
                device.discovery_status = "failed"
                device.discovery_error = str(e)
                continue
        
        # If we tried all credentials and still not discovered, mark as failed
        if device.discovery_status != "discovered":
            device.discovery_status = "failed"
            if not device.discovery_error:
                device.discovery_error = "Failed to authenticate with any credentials"
            
        logger.info(f"Completed processing device {ip_address}:{port} with status {device.discovery_status}")
        
        # Log progress
        logger.info(f"Completed depth {depth}, found {len(self.visited_ips)} devices so far")
    
    def _should_exclude(self, ip_address: str) -> bool:
        """Check if an IP address should be excluded."""
        for pattern in self.config.exclude_patterns:
            if re.match(pattern, ip_address):
                return True
        return False
    
    def _build_topology(self) -> None:
        """Build network topology map from discovered devices."""
        topology = {}
        connections = []
        
        # Create a mapping of IPs to canonical IPs (primary IP for each hostname)
        canonical_ips = {}
        hostname_to_canonical_ip = {}
        
        # First pass: identify canonical IPs for each hostname
        for ip, device in self.result.devices.items():
            if device.discovery_status != "discovered":
                continue
                
            hostname = device.hostname
            if hostname and not hostname.startswith("^") and "Invalid input" not in hostname:
                if hostname not in hostname_to_canonical_ip:
                    hostname_to_canonical_ip[hostname] = ip
                canonical_ips[ip] = hostname_to_canonical_ip[hostname]
            else:
                canonical_ips[ip] = ip  # Use itself as canonical if no hostname
        
        # Create topology map using canonical IPs
        for ip, device in self.result.devices.items():
            if device.discovery_status != "discovered":
                continue
                
            canonical_ip = canonical_ips.get(ip, ip)
            
            # Initialize empty adjacency list if not already done
            if canonical_ip not in topology:
                topology[canonical_ip] = []
            
            # Add neighbors
            for neighbor in device.neighbors:
                if "ip_address" in neighbor:
                    neighbor_ip = neighbor["ip_address"]
                    neighbor_canonical_ip = canonical_ips.get(neighbor_ip, neighbor_ip)
                    
                    # Only add if the neighbor is in our devices and not already added
                    if neighbor_ip in self.result.devices and neighbor_canonical_ip not in topology[canonical_ip]:
                        topology[canonical_ip].append(neighbor_canonical_ip)
                    
                    # Add connection details
                    connection = {
                        "source": canonical_ip,
                        "target": neighbor_canonical_ip,
                        "source_port": neighbor.get("local_interface", ""),
                        "target_port": neighbor.get("remote_interface", "")
                    }
                    
                    # Check if this connection already exists in any direction
                    exists = False
                    for existing in connections:
                        if ((existing["source"] == connection["source"] and 
                             existing["target"] == connection["target"] and
                             existing["source_port"] == connection["source_port"] and
                             existing["target_port"] == connection["target_port"]) or
                            (existing["source"] == connection["target"] and 
                             existing["target"] == connection["source"] and
                             existing["source_port"] == connection["target_port"] and
                             existing["target_port"] == connection["source_port"])):
                            exists = True
                            break
                    
                    # Only add if the connection doesn't already exist
                    if not exists:
                        connections.append(connection)
                        
                        # Update interface connection information
                        for device_interface in device.interfaces:
                            if isinstance(device_interface, dict):
                                if device_interface.get("name") == neighbor.get("local_interface"):
                                    device_interface["connected_to"] = f"{neighbor.get('hostname', neighbor_ip)}:{neighbor.get('remote_interface')}"
                                    break
                            else:  # DeviceInterface object
                                if device_interface.name == neighbor.get("local_interface"):
                                    device_interface.connected_to = f"{neighbor.get('hostname', neighbor_ip)}:{neighbor.get('remote_interface')}"
                                    break
        
        # Store in result
        self.result.topology = topology
        self.result.connections = connections
        
        # Log deduplication results
        logger.info(f"Device deduplication: {len(self.hostname_to_ips)} unique hostnames across {len(self.result.devices)} IP addresses")
        for hostname, ips in self.hostname_to_ips.items():
            if len(ips) > 1:
                logger.info(f"Device {hostname} has multiple IPs: {', '.join(ips)}")
                
        logger.info(f"Built topology map with {len(topology)} devices and {len(connections)} connections")
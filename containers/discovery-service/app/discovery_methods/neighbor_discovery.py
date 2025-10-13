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
                    
                    # Update status
                    device.discovery_status = "discovered"
                    device.credentials_used = {
                        "username": credential["username"],
                        "auth_type": credential.get("auth_type", "password"),
                        "port": str(port)  # Convert port to string to avoid serialization issues
                    }
                    
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
        
        # Create topology map
        for ip, device in self.result.devices.items():
            if device.discovery_status != "discovered":
                continue
                
            # Initialize empty adjacency list
            topology[ip] = []
            
            # Add neighbors
            for neighbor in device.neighbors:
                if "ip_address" in neighbor and neighbor["ip_address"] in self.result.devices:
                    neighbor_ip = neighbor["ip_address"]
                    topology[ip].append(neighbor_ip)
                    
                    # Add connection details
                    connection = {
                        "source": ip,
                        "target": neighbor_ip,
                        "source_port": neighbor.get("local_interface"),
                        "target_port": neighbor.get("remote_interface")
                    }
                    
                    # Check if this connection already exists in reverse
                    reverse_exists = False
                    for existing in connections:
                        if (existing["source"] == neighbor_ip and 
                            existing["target"] == ip and
                            existing["source_port"] == neighbor.get("remote_interface") and
                            existing["target_port"] == neighbor.get("local_interface")):
                            reverse_exists = True
                            break
                    
                    if not reverse_exists:
                        connections.append(connection)
                        
                        # Update interface connection information
                        for device_interface in device.interfaces:
                            if device_interface.name == neighbor.get("local_interface"):
                                device_interface.connected_to = f"{neighbor.get('hostname', neighbor_ip)}:{neighbor.get('remote_interface')}"
                                break
        
        self.result.topology = topology
        self.result.connections = connections
        logger.info(f"Built topology map with {len(topology)} devices and {len(connections)} connections")
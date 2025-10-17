"""
Subnet scan discovery method implementation.

This method discovers network devices by scanning IP ranges
and attempting to connect to devices found.
"""

import asyncio
import ipaddress
import socket
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from app.discovery_methods.base import DiscoveryMethodBase
from app.models import DiscoveryConfig, DiscoveryResult, Device, Credential
from app.device_handler import DeviceHandler

logger = logging.getLogger(__name__)


class SubnetScanDiscovery(DiscoveryMethodBase):
    """Subnet scan-based network discovery method."""
    
    @property
    def name(self) -> str:
        """Get the name of this discovery method."""
        return "subnet_scan"
    
    @property
    def description(self) -> str:
        """Get the description of this discovery method."""
        return "Discovers network devices by scanning IP subnets"
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize subnet scan discovery with configuration."""
        super().__init__(config)
        self.discovered_ips: Set[str] = set()
        
        # Handle the case when config is None (used during registration)
        if config is None:
            self.connection_semaphore = None
            self.device_handler = None
            self.subnets = []
            return
            
        self.connection_semaphore = asyncio.Semaphore(config.concurrent_connections)
        
        # Initialize device handler
        self.device_handler = DeviceHandler(timeout=config.timeout)
        
        # Extract subnets from seed devices
        self.subnets = []
        for seed in config.seed_devices:
            if '/' in seed:  # CIDR notation
                self.subnets.append(seed)
            else:
                # Assume it's a single IP and add /32
                self.subnets.append(f"{seed}/32")
    
    async def run(self) -> DiscoveryResult:
        """Run subnet scan discovery process."""
        self.result.start_time = datetime.now()
        
        try:
            # Discover live hosts in subnets
            live_hosts = await self._discover_hosts()
            
            # Process discovered hosts
            tasks = [self.process_device(ip) for ip in live_hosts]
            await asyncio.gather(*tasks)
                
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
            
        except Exception as e:
            logger.error(f"Discovery process error: {str(e)}")
            
        finally:
            self.result.end_time = datetime.now()
            return self.result
    
    async def _discover_hosts(self) -> List[str]:
        """Discover live hosts in the specified subnets."""
        from app.discovery_methods.ip_reachability import IPReachabilityDiscovery
        
        try:
            # Use the new IP reachability module
            ip_reachability = IPReachabilityDiscovery(self.config)
            
            # Get reachability results
            reachability_results = await ip_reachability.discover_reachable_hosts(
                self.subnets,
                probe_ports=[22, 443],  # Default probe ports
                concurrency=self.config.concurrent_connections
            )
            
            # Save reachability results to a file if job_id is available
            if hasattr(self.config, 'job_id') and self.config.job_id:
                job_id = self.config.job_id
                from app.utils import write_artifact
                write_artifact(job_id, "reachability_matrix.json", reachability_results)
            
            # Extract live hosts from results (hosts that are ICMP reachable or have open ports)
            live_hosts = []
            for host_result in reachability_results["results"]:
                ip = host_result["ip"]
                icmp_reachable = host_result["icmp_reachable"]
                open_ports = host_result["open_ports"]
                
                if icmp_reachable or open_ports:
                    live_hosts.append(ip)
            
            # Update stats with reachability summary
            self.result.stats.update(reachability_results["summary"])
            
            return live_hosts
            
        except Exception as e:
            logger.error(f"Error discovering hosts: {str(e)}")
            return []
    
    async def _fping_scan(self, targets: List[str]) -> List[str]:
        """Scan a list of IP addresses using fping."""
        if not targets:
            return []
            
        try:
            # Create a temporary file with targets
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp:
                temp.write('\n'.join(targets))
                temp_filename = temp.name
            
            # Run fping with the target file
            cmd = [
                "fping", 
                "-a",  # Show only alive hosts
                "-f", temp_filename
            ]
            
            # Run the command asynchronously
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            # Clean up temp file
            import os
            os.unlink(temp_filename)
            
            # Parse results (alive hosts from stdout)
            alive = []
            if stdout:
                alive = [line.strip() for line in stdout.decode().split('\n') if line.strip()]
            
            return alive
            
        except Exception as e:
            logger.error(f"Error during fping scan: {str(e)}")
            return []
    
    async def process_device(self, ip_address: str) -> None:
        """Process a single device: connect, extract config."""
        if ip_address in self.discovered_ips:
            return
            
        self.discovered_ips.add(ip_address)
        device = Device(ip_address=ip_address)
        self.result.devices[ip_address] = device
        
        # Try to connect with available credentials
        connected = False
        
        async with self.connection_semaphore:
            for cred_dict in self.config.credentials:
                try:
                    # Create credential object
                    credential = Credential(**cred_dict)
                    
                    # Try to detect device type
                    device_type = await self.device_handler.detect_device_type(ip_address, credential)
                    
                    # Get device info
                    device_info = await self.device_handler.get_device_info(ip_address, credential, device_type)
                    if device_info:
                        connected = True
                        # Update device with collected information
                        for key, value in device_info.items():
                            if hasattr(device, key):
                                setattr(device, key, value)
                        
                        # Record successful credentials
                        device.credentials_used = {
                            "username": credential.username,
                            "auth_type": credential.auth_type
                        }
                        
                        # Extract device configuration
                        device.config = await self.device_handler.get_device_config(
                            ip_address, credential, device_type
                        )
                        
                        # Mark as successfully discovered
                        device.discovery_status = "discovered"
                        break
                    
                except Exception as e:
                    logger.error(f"Error processing device {ip_address}: {str(e)}")
                    device.discovery_status = "failed"
                    device.discovery_error = str(e)
        
        # If all credential attempts failed
        if not connected and device.discovery_status == "pending":
            device.discovery_status = "failed"
            device.discovery_error = "Authentication failed with all credentials"
            
        # Update last seen timestamp
        device.last_seen = datetime.now()
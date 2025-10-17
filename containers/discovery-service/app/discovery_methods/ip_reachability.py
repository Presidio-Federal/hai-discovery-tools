"""
IP Reachability discovery method implementation.

This module provides functionality to discover reachable hosts using ICMP and TCP port probes.
"""

import asyncio
import ipaddress
import socket
import logging
import subprocess
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple

from loguru import logger

from app.discovery_methods.base import DiscoveryMethodBase
from app.models import DiscoveryConfig, DiscoveryResult, Device

# Configure standard logging
logging.basicConfig(level=logging.INFO)
std_logger = logging.getLogger(__name__)

# Initialize loguru logger
logger.remove()
logger.add(
    sink=sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message} | {extra}",
    serialize=True,  # Output as JSON
)


class IPReachabilityDiscovery(DiscoveryMethodBase):
    """IP Reachability discovery method."""
    
    @property
    def name(self) -> str:
        """Get the name of this discovery method."""
        return "ip_reachability"
    
    @property
    def description(self) -> str:
        """Get the description of this discovery method."""
        return "Discovers reachable hosts using ICMP and TCP port probes"
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize IP reachability discovery with configuration."""
        super().__init__(config)
        self.discovered_ips: Set[str] = set()
        
        # Handle the case when config is None (used during registration)
        if config is None:
            self.connection_semaphore = None
            self.subnets = []
            self.probe_ports = [22, 443]
            self.concurrency = 200
            return
            
        # Extract subnets from seed devices
        self.subnets = []
        for seed in config.seed_devices:
            if '/' in seed:  # CIDR notation
                self.subnets.append(seed)
            else:
                # Assume it's a single IP and add /32
                self.subnets.append(f"{seed}/32")
        
        # Get probe ports from config or use defaults
        self.probe_ports = config.stats.get("probe_ports", [22, 443])
        
        # Get concurrency from config or use default
        self.concurrency = config.stats.get("concurrency", 200)
        
        # Create semaphore for limiting concurrent operations
        self.connection_semaphore = asyncio.Semaphore(self.concurrency)
    
    async def run(self) -> DiscoveryResult:
        """Run IP reachability discovery process."""
        self.result.start_time = datetime.now()
        start_time = time.time()
        
        try:
            # Discover reachable hosts
            reachability_results = await self.discover_reachable_hosts(
                self.subnets,
                self.probe_ports,
                self.concurrency
            )
            
            # Store results in the discovery result
            self.result.stats = reachability_results
            
            # Create Device objects for reachable hosts
            for host_result in reachability_results["results"]:
                ip = host_result["ip"]
                icmp_reachable = host_result["icmp_reachable"]
                open_ports = host_result["open_ports"]
                
                # Only add to devices if reachable via ICMP or has open ports
                if icmp_reachable or open_ports:
                    device = Device(
                        ip_address=ip,
                        discovery_status="reachable" if icmp_reachable or open_ports else "unreachable"
                    )
                    
                    # Add port information to device stats
                    device_stats = {
                        "icmp_reachable": icmp_reachable,
                        "open_ports": open_ports
                    }
                    
                    # Store stats in device
                    device.stats = device_stats
                    
                    # Add device to result
                    self.result.devices[ip] = device
            
            # Update final statistics
            self.result.total_devices_found = len(self.result.devices)
            self.result.successful_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status == "reachable"
            )
            self.result.failed_connections = sum(
                1 for device in self.result.devices.values() 
                if device.discovery_status == "unreachable"
            )
            
            # Update status
            self.result.status = "completed"
            
        except Exception as e:
            logger.error(f"IP reachability discovery error: {str(e)}")
            self.result.status = "failed"
            self.result.stats["error"] = str(e)
            
        finally:
            self.result.end_time = datetime.now()
            duration = time.time() - start_time
            self.result.stats["duration_sec"] = duration
            return self.result
    
    async def discover_reachable_hosts(
        self, 
        subnets: List[str], 
        probe_ports: List[int] = [22, 443], 
        concurrency: int = 200
    ) -> Dict[str, Any]:
        """
        Discover reachable hosts in the specified subnets.
        
        Args:
            subnets: List of subnets in CIDR notation
            probe_ports: List of TCP ports to probe
            concurrency: Maximum number of concurrent operations
            
        Returns:
            Dictionary with reachability results
        """
        # Deduplicate subnets
        unique_subnets = list(set(subnets))
        
        # Initialize results
        results = []
        total_hosts = 0
        icmp_reachable = 0
        ports_summary = {port: 0 for port in probe_ports}
        
        # Process each subnet
        for subnet in unique_subnets:
            try:
                # Parse subnet
                network = ipaddress.ip_network(subnet, strict=False)
                total_hosts += network.num_addresses - 2  # Exclude network and broadcast addresses
                
                # For small networks, scan all hosts at once
                if network.num_addresses <= 256:
                    targets = [str(ip) for ip in network.hosts()]
                    subnet_results = await self._scan_hosts(targets, probe_ports, concurrency)
                    results.extend(subnet_results)
                else:
                    # For larger networks, scan in chunks
                    chunk_size = 256
                    all_hosts = list(network.hosts())
                    
                    for i in range(0, len(all_hosts), chunk_size):
                        chunk = all_hosts[i:i+chunk_size]
                        targets = [str(ip) for ip in chunk]
                        subnet_results = await self._scan_hosts(targets, probe_ports, concurrency)
                        results.extend(subnet_results)
                
            except Exception as e:
                logger.error(f"Error scanning subnet {subnet}: {str(e)}")
        
        # Calculate summary statistics
        for host_result in results:
            if host_result["icmp_reachable"]:
                icmp_reachable += 1
            
            for port in host_result["open_ports"]:
                ports_summary[port] += 1
        
        # Build the final result
        return {
            "results": results,
            "summary": {
                "total_scanned": total_hosts,
                "icmp_reachable": icmp_reachable,
                **{f"port_{port}_open": count for port, count in ports_summary.items()}
            },
            "duration_sec": 0,  # Will be updated by the caller
            "timestamp": datetime.now().isoformat()
        }
    
    async def _scan_hosts(self, targets: List[str], probe_ports: List[int], concurrency: int) -> List[Dict[str, Any]]:
        """
        Scan a list of hosts for ICMP reachability and open TCP ports.
        
        Args:
            targets: List of IP addresses to scan
            probe_ports: List of TCP ports to probe
            concurrency: Maximum number of concurrent operations
            
        Returns:
            List of dictionaries with scan results for each host
        """
        if not targets:
            return []
        
        # Create semaphore for limiting concurrent operations
        semaphore = asyncio.Semaphore(concurrency)
        
        # First, check ICMP reachability
        icmp_results = await self._fping_scan(targets)
        icmp_reachable = set(icmp_results)
        
        # Create tasks for TCP port scanning
        scan_tasks = []
        for ip in targets:
            task = self._scan_host_ports(ip, probe_ports, icmp_reachable, semaphore)
            scan_tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*scan_tasks)
        
        return results
    
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
            
            # Clean up the temporary file
            import os
            os.unlink(temp_filename)
            
            # Parse the output
            if stdout:
                # fping returns alive hosts one per line
                alive_hosts = stdout.decode().strip().split('\n')
                # Filter out empty lines
                alive_hosts = [host for host in alive_hosts if host]
                return alive_hosts
            
            return []
            
        except Exception as e:
            logger.error(f"Error running fping: {str(e)}")
            
            # Fallback to aioping for better performance
            try:
                import aioping
                from async_timeout import timeout
                
                logger.info("Falling back to aioping")
                alive_hosts = []
                
                # Use aioping for asynchronous ping
                async def ping_host(ip):
                    try:
                        async with timeout(2):  # 2 second timeout
                            delay = await aioping.ping(ip, timeout=1)
                            return ip if delay is not None else None
                    except (aioping.TimeoutError, asyncio.TimeoutError):
                        return None
                    except Exception as e:
                        logger.debug(f"Error pinging {ip}: {str(e)}")
                        return None
                
                # Create a semaphore to limit concurrency
                semaphore = asyncio.Semaphore(min(self.concurrency, 200))
                
                # Wrap ping_host with semaphore
                async def ping_with_semaphore(ip):
                    async with semaphore:
                        return await ping_host(ip)
                
                # Run ping for each host with concurrency limit
                tasks = [ping_with_semaphore(ip) for ip in targets]
                results = await asyncio.gather(*tasks)
                alive_hosts = [ip for ip in results if ip]
                
                return alive_hosts
                
            except ImportError:
                # Fallback to standard ping if aioping is not available
                logger.info("aioping not available, falling back to standard ping")
                alive_hosts = []
                
                # Use asyncio.gather to run pings in parallel
                async def ping_host(ip):
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "ping", "-c", "1", "-W", "1", ip,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        await proc.communicate()
                        if proc.returncode == 0:
                            return ip
                        return None
                    except Exception:
                        return None
                
                # Create a semaphore to limit concurrency
                semaphore = asyncio.Semaphore(min(self.concurrency, 50))
                
                # Wrap ping_host with semaphore
                async def ping_with_semaphore(ip):
                    async with semaphore:
                        return await ping_host(ip)
                
                # Run ping for each host with concurrency limit
                tasks = [ping_with_semaphore(ip) for ip in targets]
                results = await asyncio.gather(*tasks)
                alive_hosts = [ip for ip in results if ip]
                
                return alive_hosts
    
    async def _scan_host_ports(
        self, 
        ip: str, 
        ports: List[int], 
        icmp_reachable: Set[str],
        semaphore: asyncio.Semaphore
    ) -> Dict[str, Any]:
        """
        Scan a host for open TCP ports.
        
        Args:
            ip: IP address to scan
            ports: List of TCP ports to probe
            icmp_reachable: Set of IPs that are reachable via ICMP
            semaphore: Semaphore for limiting concurrent operations
            
        Returns:
            Dictionary with scan results for the host
        """
        is_icmp_reachable = ip in icmp_reachable
        open_ports = []
        
        # Scan ports
        port_tasks = []
        for port in ports:
            task = self._check_tcp_port(ip, port, semaphore)
            port_tasks.append(task)
        
        # Wait for all port checks to complete
        port_results = await asyncio.gather(*port_tasks)
        
        # Collect open ports
        for port, is_open in zip(ports, port_results):
            if is_open:
                open_ports.append(port)
        
        # Return results for this host
        return {
            "ip": ip,
            "icmp_reachable": is_icmp_reachable,
            "open_ports": open_ports
        }
    
    async def _check_tcp_port(self, ip: str, port: int, semaphore: asyncio.Semaphore) -> bool:
        """
        Check if a TCP port is open.
        
        Args:
            ip: IP address to check
            port: TCP port to check
            semaphore: Semaphore for limiting concurrent operations
            
        Returns:
            True if the port is open, False otherwise
        """
        async with semaphore:
            # First try with asyncssh for SSH ports (more reliable)
            if port == 22:
                try:
                    import asyncssh
                    from async_timeout import timeout
                    
                    async with timeout(3):  # 3 second timeout
                        try:
                            # Just check if port is open, don't try to authenticate
                            await asyncssh.connect(
                                ip, 
                                port=port, 
                                known_hosts=None, 
                                username='invalid_user_just_checking_port',
                                password='invalid_password_just_checking_port',
                                connect_timeout=2
                            )
                            return True
                        except asyncssh.DisconnectError:
                            # If we get a disconnect error, the port is open but auth failed
                            return True
                        except (asyncssh.ConnectionRefusedError, asyncssh.TimeoutError):
                            return False
                except ImportError:
                    # Fall back to standard TCP check if asyncssh is not available
                    pass
            
            # Standard TCP connection check for all ports
            try:
                # Create a future that will be set when the connection is made
                future = asyncio.open_connection(ip, port)
                
                # Wait for the connection with a timeout
                reader, writer = await asyncio.wait_for(future, timeout=2.0)
                
                # Close the connection
                writer.close()
                await writer.wait_closed()
                
                return True
                
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                return False
            except Exception as e:
                logger.error(f"Error checking port {port} on {ip}: {str(e)}")
                return False

# Fix missing import
import sys

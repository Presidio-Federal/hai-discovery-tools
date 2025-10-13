"""
SNMP-based discovery method implementation.

This method discovers network devices using SNMP protocol,
which can be useful for devices that don't support SSH.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
import ipaddress
import socket

from pysnmp.hlapi import (
    SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, nextCmd, getCmd
)
from pysnmp.error import PySnmpError

from .base import DiscoveryMethodBase
from ..models import DiscoveryConfig, DiscoveryResult, Device, DeviceInterface

logger = logging.getLogger(__name__)


class SNMPDiscovery(DiscoveryMethodBase):
    """SNMP-based network discovery method."""
    
    # Common SNMP OIDs for network discovery
    OIDS = {
        "sysDescr": "1.3.6.1.2.1.1.1.0",        # System description
        "sysName": "1.3.6.1.2.1.1.5.0",         # System name
        "sysLocation": "1.3.6.1.2.1.1.6.0",     # System location
        "sysContact": "1.3.6.1.2.1.1.4.0",      # System contact
        "sysObjectID": "1.3.6.1.2.1.1.2.0",     # System object ID
        "ifTable": "1.3.6.1.2.1.2.2",           # Interface table
        "ifDescr": "1.3.6.1.2.1.2.2.1.2",       # Interface description
        "ifType": "1.3.6.1.2.1.2.2.1.3",        # Interface type
        "ifPhysAddress": "1.3.6.1.2.1.2.2.1.6", # Interface MAC address
        "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7", # Interface admin status
        "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",  # Interface operational status
        "ipAddrTable": "1.3.6.1.2.1.4.20",      # IP address table
        "ipNetToMediaTable": "1.3.6.1.2.1.4.22", # ARP table
        "cdpCacheTable": "1.3.6.1.4.1.9.9.23.1.2.1", # CDP cache table (Cisco)
        "lldpRemTable": "1.0.8802.1.1.2.1.4.1"  # LLDP remote table
    }
    
    @property
    def name(self) -> str:
        """Get the name of this discovery method."""
        return "snmp_discovery"
    
    @property
    def description(self) -> str:
        """Get the description of this discovery method."""
        return "Discovers network devices using SNMP protocol"
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize SNMP discovery with configuration."""
        super().__init__(config)
        self.discovered_ips: Set[str] = set()
        self.pending_ips: Set[str] = set(config.seed_devices)
        
        # Extract SNMP communities from credentials
        self.communities = []
        for cred in config.credentials:
            if "community" in cred:
                self.communities.append(cred["community"])
        
        # Add default communities if none provided
        if not self.communities:
            self.communities = ["public", "private"]
    
    async def run(self) -> DiscoveryResult:
        """Run SNMP discovery process."""
        self.result.start_time = datetime.now()
        
        try:
            current_depth = 0
            while current_depth < self.config.max_depth and self.pending_ips:
                # Get the current batch of IPs to process
                current_batch = self.pending_ips.copy()
                self.pending_ips = set()
                
                # Process the current batch
                tasks = [self.process_device(ip) for ip in current_batch]
                await asyncio.gather(*tasks)
                
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
            
        except Exception as e:
            logger.error(f"Discovery process error: {str(e)}")
            
        finally:
            self.result.end_time = datetime.now()
            return self.result
    
    async def process_device(self, ip_address: str) -> None:
        """Process a single device using SNMP."""
        if ip_address in self.discovered_ips:
            return
            
        self.discovered_ips.add(ip_address)
        device = Device(ip_address=ip_address)
        self.result.devices[ip_address] = device
        
        # Check if device responds to SNMP
        if not await self._check_snmp_reachable(ip_address):
            device.discovery_status = "unreachable"
            device.discovery_error = "SNMP not reachable"
            return
        
        # Try each community string
        for community in self.communities:
            try:
                # Get basic device information
                device_info = await self._get_device_info(ip_address, community)
                if device_info:
                    # Update device with collected information
                    for key, value in device_info.items():
                        if hasattr(device, key):
                            setattr(device, key, value)
                    
                    # Get interfaces
                    interfaces = await self._get_interfaces(ip_address, community)
                    device.interfaces = interfaces
                    
                    # Get neighbors
                    neighbors = []
                    if "cdp" in self.config.discovery_protocols:
                        cdp_neighbors = await self._get_cdp_neighbors(ip_address, community)
                        neighbors.extend(cdp_neighbors)
                    
                    if "lldp" in self.config.discovery_protocols:
                        lldp_neighbors = await self._get_lldp_neighbors(ip_address, community)
                        neighbors.extend(lldp_neighbors)
                    
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
                    break
                
            except Exception as e:
                logger.debug(f"SNMP error with community {community} for {ip_address}: {str(e)}")
        
        # If all community attempts failed
        if device.discovery_status == "pending":
            device.discovery_status = "failed"
            device.discovery_error = "SNMP authentication failed with all communities"
            
        # Update last seen timestamp
        device.last_seen = datetime.now()
    
    async def _check_snmp_reachable(self, ip_address: str) -> bool:
        """Check if a device is reachable via SNMP."""
        try:
            # Check if UDP port 161 is open
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)  # Quick timeout for port check
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, sock.connect, (ip_address, 161))
            sock.close()
            return True
            
        except (socket.timeout, ConnectionRefusedError):
            return False
            
        except Exception:
            return False
    
    async def _get_device_info(self, ip_address: str, community: str) -> Dict[str, Any]:
        """Get basic device information using SNMP."""
        device_info = {}
        
        try:
            # Get system description
            sys_descr = await self._get_snmp_value(ip_address, community, self.OIDS["sysDescr"])
            if sys_descr:
                device_info["platform"] = self._extract_platform(sys_descr)
                device_info["os_version"] = self._extract_version(sys_descr)
                device_info["model"] = self._extract_model(sys_descr)
            
            # Get system name
            sys_name = await self._get_snmp_value(ip_address, community, self.OIDS["sysName"])
            if sys_name:
                device_info["hostname"] = sys_name
            
            # Get system object ID
            sys_object_id = await self._get_snmp_value(ip_address, community, self.OIDS["sysObjectID"])
            if sys_object_id:
                vendor = self._extract_vendor_from_oid(sys_object_id)
                if vendor:
                    device_info["vendor"] = vendor
            
            return device_info
            
        except Exception as e:
            logger.debug(f"Error getting device info for {ip_address}: {str(e)}")
            return {}
    
    async def _get_interfaces(self, ip_address: str, community: str) -> List[DeviceInterface]:
        """Get interface information using SNMP."""
        interfaces = []
        
        try:
            # Get interface descriptions
            if_descr_table = await self._get_snmp_table(ip_address, community, self.OIDS["ifDescr"])
            
            # Get interface operational status
            if_oper_status = await self._get_snmp_table(ip_address, community, self.OIDS["ifOperStatus"])
            
            # Get interface MAC addresses
            if_phys_addr = await self._get_snmp_table(ip_address, community, self.OIDS["ifPhysAddress"])
            
            # Get IP address table
            ip_addr_table = await self._get_snmp_table(ip_address, community, self.OIDS["ipAddrTable"])
            
            # Create interface objects
            for idx, descr in if_descr_table.items():
                interface = DeviceInterface(name=descr)
                
                # Set status
                if idx in if_oper_status:
                    status_val = if_oper_status[idx]
                    interface.status = "up" if status_val == "1" else "down"
                
                # Set MAC address
                if idx in if_phys_addr:
                    interface.mac_address = if_phys_addr[idx]
                
                # Find IP address for this interface
                # This is simplified; in reality, mapping IPs to interfaces requires more complex logic
                
                interfaces.append(interface)
            
            return interfaces
            
        except Exception as e:
            logger.debug(f"Error getting interfaces for {ip_address}: {str(e)}")
            return []
    
    async def _get_cdp_neighbors(self, ip_address: str, community: str) -> List[Dict[str, Any]]:
        """Get CDP neighbors using SNMP."""
        neighbors = []
        
        try:
            # Get CDP cache table
            cdp_table = await self._get_snmp_table(ip_address, community, self.OIDS["cdpCacheTable"])
            
            # Process CDP table entries
            # This is simplified; in reality, CDP table parsing via SNMP is more complex
            
            return neighbors
            
        except Exception as e:
            logger.debug(f"Error getting CDP neighbors for {ip_address}: {str(e)}")
            return []
    
    async def _get_lldp_neighbors(self, ip_address: str, community: str) -> List[Dict[str, Any]]:
        """Get LLDP neighbors using SNMP."""
        neighbors = []
        
        try:
            # Get LLDP remote table
            lldp_table = await self._get_snmp_table(ip_address, community, self.OIDS["lldpRemTable"])
            
            # Process LLDP table entries
            # This is simplified; in reality, LLDP table parsing via SNMP is more complex
            
            return neighbors
            
        except Exception as e:
            logger.debug(f"Error getting LLDP neighbors for {ip_address}: {str(e)}")
            return []
    
    async def _get_snmp_value(self, ip_address: str, community: str, oid: str) -> Optional[str]:
        """Get a single SNMP value."""
        try:
            loop = asyncio.get_event_loop()
            
            # Create SNMP GET request
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip_address, 161), timeout=self.config.timeout, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )
            
            # Execute SNMP GET request
            errorIndication, errorStatus, errorIndex, varBinds = await loop.run_in_executor(
                None,
                lambda: next(iterator)
            )
            
            if errorIndication:
                logger.debug(f"SNMP error: {errorIndication}")
                return None
                
            if errorStatus:
                logger.debug(f"SNMP error: {errorStatus.prettyPrint()}")
                return None
                
            # Extract value from response
            for varBind in varBinds:
                return str(varBind[1])
                
            return None
            
        except PySnmpError as e:
            logger.debug(f"PySnmp error: {str(e)}")
            return None
            
        except Exception as e:
            logger.debug(f"Error in SNMP get: {str(e)}")
            return None
    
    async def _get_snmp_table(self, ip_address: str, community: str, oid: str) -> Dict[str, str]:
        """Get an SNMP table."""
        result = {}
        
        try:
            loop = asyncio.get_event_loop()
            
            # Create SNMP GETNEXT request
            iterator = nextCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip_address, 161), timeout=self.config.timeout, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False
            )
            
            # Execute SNMP GETNEXT requests
            while True:
                errorIndication, errorStatus, errorIndex, varBinds = await loop.run_in_executor(
                    None,
                    lambda: next(iterator)
                )
                
                if errorIndication:
                    logger.debug(f"SNMP error: {errorIndication}")
                    break
                    
                if errorStatus:
                    logger.debug(f"SNMP error: {errorStatus.prettyPrint()}")
                    break
                
                # Extract values from response
                for varBind in varBinds:
                    # Get OID and value
                    full_oid = str(varBind[0])
                    value = str(varBind[1])
                    
                    # Extract index from OID
                    if full_oid.startswith(oid):
                        idx = full_oid[len(oid) + 1:]
                        result[idx] = value
                    else:
                        # We've gone past the desired table
                        return result
            
            return result
            
        except PySnmpError as e:
            logger.debug(f"PySnmp error: {str(e)}")
            return result
            
        except Exception as e:
            logger.debug(f"Error in SNMP walk: {str(e)}")
            return result
    
    def _extract_platform(self, sys_descr: str) -> Optional[str]:
        """Extract platform from system description."""
        # This is a simplified implementation
        if "cisco" in sys_descr.lower():
            return "cisco"
        elif "juniper" in sys_descr.lower():
            return "juniper"
        elif "arista" in sys_descr.lower():
            return "arista"
        return None
    
    def _extract_version(self, sys_descr: str) -> Optional[str]:
        """Extract OS version from system description."""
        # This is a simplified implementation
        import re
        
        # Try to find version strings like "Version 12.4(24)T"
        version_match = re.search(r"Version\s+([0-9\.]+)", sys_descr)
        if version_match:
            return version_match.group(1)
            
        return None
    
    def _extract_model(self, sys_descr: str) -> Optional[str]:
        """Extract model from system description."""
        # This is a simplified implementation
        import re
        
        # Try to find model strings
        model_match = re.search(r"(C\d+|ASR\d+|ISR\d+|MX\d+|EX\d+|DCS-\d+)", sys_descr)
        if model_match:
            return model_match.group(1)
            
        return None
    
    def _extract_vendor_from_oid(self, oid: str) -> Optional[str]:
        """Extract vendor from system object ID."""
        # Enterprise OIDs
        if "1.3.6.1.4.1.9." in oid:  # Cisco
            return "cisco"
        elif "1.3.6.1.4.1.2636." in oid:  # Juniper
            return "juniper"
        elif "1.3.6.1.4.1.30065." in oid:  # Arista
            return "arista"
        return None
    
    def _is_excluded(self, ip_address: str) -> bool:
        """Check if an IP address matches exclusion patterns."""
        import re
        for pattern in self.config.exclude_patterns:
            if re.match(pattern, ip_address):
                return True
        return False

"""
Data models for network discovery operations.
"""

from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime


class Credential(BaseModel):
    """Credential set for device authentication."""
    username: str
    password: str
    enable_secret: Optional[str] = None
    auth_type: str = "password"  # password, key, token


class DeviceInterface(BaseModel):
    """Network interface on a device."""
    name: str
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None
    mac_address: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    vlan: Optional[str] = None
    connected_to: Optional[str] = None
    is_trunk: bool = False
    secondary_ips: List[Dict[str, str]] = Field(default_factory=list)


class Device(BaseModel):
    """Network device discovered during the process."""
    hostname: Optional[str] = None
    ip_address: str
    platform: Optional[str] = None
    os_version: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    uptime: Optional[str] = None
    vendor: Optional[str] = None
    device_type: Optional[str] = None
    interfaces: List[Any] = Field(default_factory=list)  # Can be DeviceInterface or dict
    neighbors: List[Dict[str, Any]] = Field(default_factory=list)
    config: Optional[str] = None
    parsed_config: Optional[Dict[str, Any]] = None
    credentials_used: Optional[Dict[str, Any]] = None
    discovery_status: str = "pending"  # pending, discovered, failed, unreachable
    discovery_error: Optional[str] = None
    last_seen: datetime = Field(default_factory=datetime.now)
    all_ip_addresses: List[str] = Field(default_factory=list)  # All IPs associated with this device


class DiscoveryConfig(BaseModel):
    """Configuration for network discovery process."""
    seed_devices: List[str]
    credentials: List[Dict[str, str]]
    max_depth: int = 3
    discovery_protocols: List[str] = ["cdp", "lldp"]
    timeout: int = 60
    concurrent_connections: int = 10
    retry_count: int = 2
    exclude_patterns: List[str] = Field(default_factory=list)
    
    def parse_seed_device(self, device: str) -> Tuple[str, int]:
        """Parse seed device string to extract IP and port.
        
        Format can be:
        - IP
        - IP:PORT
        """
        if ":" in device:
            parts = device.split(":", 1)
            return parts[0], int(parts[1])
        return device, 22  # Default SSH port


class DiscoveryResult(BaseModel):
    """Results of a network discovery operation."""
    devices: Dict[str, Device] = Field(default_factory=dict)
    topology: Dict[str, List[str]] = Field(default_factory=dict)
    connections: List[Dict[str, Any]] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    total_devices_found: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)

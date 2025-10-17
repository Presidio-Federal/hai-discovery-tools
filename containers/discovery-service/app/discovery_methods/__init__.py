"""
Discovery methods package.

This package contains all discovery methods used by the network discovery service.
"""

from app.registry import DiscoveryMethodRegistry
from app.discovery_methods.neighbor_discovery import NeighborDiscovery
from app.discovery_methods.subnet_scan import SubnetScanDiscovery
from app.discovery_methods.ip_reachability import IPReachabilityDiscovery

# Register discovery methods
DiscoveryMethodRegistry.register(NeighborDiscovery)
DiscoveryMethodRegistry.register(SubnetScanDiscovery)
DiscoveryMethodRegistry.register(IPReachabilityDiscovery)

# Create a helper class for seed device introspection
class SeedDeviceIntrospection:
    """Helper class for seed device introspection."""
    
    @property
    def name(self) -> str:
        """Get the name of this discovery method."""
        return "seed_device_introspection"
    
    @property
    def description(self) -> str:
        """Get the description of this discovery method."""
        return "Introspects seed devices to extract subnets and runs IP reachability"
    
    def __init__(self, config):
        """Initialize with configuration."""
        self.config = config
    
    async def run(self):
        """Placeholder for run method."""
        # This is just a placeholder for registration
        # The actual implementation is in NetworkDiscovery._run_seed_device_discovery
        from app.models import DiscoveryResult
        return DiscoveryResult()

# Register the helper class
DiscoveryMethodRegistry.register(SeedDeviceIntrospection)
"""
Network Discovery Service.

This package provides tools for discovering network devices and extracting information.
"""

# Import registry first to avoid circular imports
from app.registry import DiscoveryMethodRegistry

# Then import discovery methods
from app.discovery_methods.neighbor_discovery import NeighborDiscovery
from app.discovery_methods.subnet_scan import SubnetScanDiscovery

# Register discovery methods
DiscoveryMethodRegistry.register(NeighborDiscovery)
DiscoveryMethodRegistry.register(SubnetScanDiscovery)
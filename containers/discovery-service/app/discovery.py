"""
Core network discovery implementation.

This module provides a unified interface for running discovery operations.
"""

import logging
from typing import Dict, Type, List, Any, Optional
from datetime import datetime

from app.models import DiscoveryConfig, DiscoveryResult
from app.registry import DiscoveryMethodRegistry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NetworkDiscovery:
    """
    Network discovery engine that handles the discovery process
    using the specified method.
    """
    
    def __init__(self, config: DiscoveryConfig, method_name: str = "neighbor_discovery"):
        """Initialize the discovery engine with configuration and method."""
        self.config = config
        self.method_name = method_name
        
        # Get the discovery method
        method_class = DiscoveryMethodRegistry.get_method(method_name)
        if not method_class:
            raise ValueError(f"Unknown discovery method: {method_name}")
        
        self.method = method_class(config)
        
    async def run_discovery(self) -> DiscoveryResult:
        """Run the discovery process using the configured method."""
        logger.info(f"Starting discovery using method: {self.method_name}")
        
        try:
            # Run the discovery method
            result = await self.method.run()
            logger.info(f"Discovery completed. Found {result.total_devices_found} devices.")
            return result
            
        except Exception as e:
            logger.error(f"Discovery process error: {str(e)}")
            # Return an empty result with error information
            result = DiscoveryResult()
            result.start_time = datetime.now()
            result.end_time = datetime.now()
            result.stats = {"error": str(e)}
            return result
"""
Base class for discovery methods.

This module provides a base class for all discovery methods.
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from app.models import DiscoveryConfig, DiscoveryResult

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscoveryMethodBase(ABC):
    """Base class for all discovery methods."""
    
    def __init__(self, config: DiscoveryConfig):
        """Initialize with discovery configuration."""
        self.config = config
        self.result = DiscoveryResult()
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the discovery method."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Return a description of the discovery method."""
        pass
    
    @abstractmethod
    async def run(self) -> DiscoveryResult:
        """Run the discovery process."""
        pass
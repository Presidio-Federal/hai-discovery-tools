"""
Registry for discovery methods.

This module provides a registry for discovery methods to avoid circular imports.
"""

import logging
from typing import Dict, Type, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscoveryMethodRegistry:
    """Registry of available discovery methods."""
    
    _methods = {}
    
    @classmethod
    def register(cls, method_class):
        """Register a discovery method."""
        # Avoid circular imports by creating a temporary instance
        # We only need the name and don't need to run any methods
        try:
            instance = method_class(None)
            cls._methods[instance.name] = method_class
        except Exception as e:
            # Log the error but don't crash during registration
            print(f"Error registering discovery method {method_class.__name__}: {str(e)}")
            # Use the class name as a fallback
            cls._methods[method_class.__name__.lower()] = method_class
    
    @classmethod
    def get_method(cls, name: str):
        """Get a discovery method by name."""
        return cls._methods.get(name)
    
    @classmethod
    def list_methods(cls) -> List[Dict[str, str]]:
        """List all registered discovery methods."""
        result = []
        for name, method_class in cls._methods.items():
            # Create a temporary instance just to get the description
            instance = method_class(None)
            result.append({
                "name": name,
                "description": instance.description
            })
        return result

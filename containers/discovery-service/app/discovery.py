"""
Core network discovery implementation.

This module provides a unified interface for running discovery operations.
"""

import os
import json
import logging
from typing import Dict, Type, List, Any, Optional
from datetime import datetime

from app.models import DiscoveryConfig, DiscoveryResult
from app.registry import DiscoveryMethodRegistry
from app.utils import write_artifact
from loguru import logger as loguru_logger

# Configure logging
logging.basicConfig(level=logging.INFO)
std_logger = logging.getLogger(__name__)

# Configure loguru logger
loguru_logger.remove()
loguru_logger.add(
    sink=lambda msg: print(msg),
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message} | {extra}",
    serialize=True,  # Output as JSON
)


class NetworkDiscovery:
    """
    Network discovery engine that handles the discovery process
    using the specified method.
    """
    
    def __init__(self, config: DiscoveryConfig, method_name: str = "neighbor_discovery"):
        """Initialize the discovery engine with configuration and method."""
        self.config = config
        self.method_name = method_name
        
        # Get the discovery method based on mode if not explicitly provided
        if method_name == "auto":
            self.method_name = self._get_method_for_mode(config.mode)
        
        # Get the discovery method
        method_class = DiscoveryMethodRegistry.get_method(self.method_name)
        if not method_class:
            raise ValueError(f"Unknown discovery method: {self.method_name}")
        
        self.method = method_class(config)
    
    def _get_method_for_mode(self, mode: str) -> str:
        """Get the appropriate discovery method for the given mode."""
        if mode == "subnet":
            return "ip_reachability"
        elif mode == "seed-device":
            return "seed_device_introspection"
        else:  # full-pipeline or any other value
            return "neighbor_discovery"
    
    async def run_discovery(self) -> DiscoveryResult:
        """Run the discovery process using the configured method."""
        std_logger.info(f"Starting discovery using method: {self.method_name}")
        
        # Log with loguru for structured logging
        loguru_logger.info(
            "Starting discovery", 
            job_id=self.config.job_id,
            mode=self.config.mode,
            method=self.method_name
        )
        
        try:
            if self.config.mode == "subnet":
                # Run IP reachability discovery
                return await self._run_subnet_discovery()
                
            elif self.config.mode == "seed-device":
                # Run seed device introspection followed by IP reachability
                return await self._run_seed_device_discovery()
                
            else:  # full-pipeline or any other value
                # Run the full discovery pipeline
                return await self._run_full_pipeline_discovery()
            
        except Exception as e:
            std_logger.error(f"Discovery process error: {str(e)}")
            loguru_logger.error(f"Discovery failed", job_id=self.config.job_id, error=str(e))
            
            # Return an empty result with error information
            result = DiscoveryResult()
            result.start_time = datetime.now()
            result.end_time = datetime.now()
            result.status = "failed"
            result.stats = {"error": str(e)}
            return result
    
    async def _run_subnet_discovery(self) -> DiscoveryResult:
        """Run IP reachability discovery on the specified subnets."""
        from app.discovery_methods.ip_reachability import IPReachabilityDiscovery
        
        # Create IP reachability discovery instance
        ip_reachability = IPReachabilityDiscovery(self.config)
        
        # Run IP reachability discovery
        result = await ip_reachability.run()
        
        # Save results to file
        if self.config.job_id:
            artifact_path = write_artifact(
                self.config.job_id, 
                "reachability_matrix.json", 
                result.stats
            )
            
            # Add artifact path to result stats
            result.stats["artifact"] = artifact_path
        
        # Log completion
        loguru_logger.info(
            "IP reachability discovery completed",
            job_id=self.config.job_id,
            total_scanned=result.stats.get("summary", {}).get("total_scanned", 0),
            icmp_reachable=result.stats.get("summary", {}).get("icmp_reachable", 0),
            ssh_open=result.stats.get("summary", {}).get("port_22_open", 0),
            https_open=result.stats.get("summary", {}).get("port_443_open", 0)
        )
        
        return result
    
    async def _run_seed_device_discovery(self) -> DiscoveryResult:
        """Run seed device introspection followed by IP reachability."""
        from app.discovery_methods.seed_device_helper import introspect_seed_devices
        from app.discovery_methods.ip_reachability import IPReachabilityDiscovery
        
        # Initialize result
        result = DiscoveryResult()
        result.start_time = datetime.now()
        
        try:
            # Extract subnets from seed devices
            subnets = await introspect_seed_devices(self.config)
            
            # Log extracted subnets
            loguru_logger.info(
                f"Extracted {len(subnets)} subnets from seed devices",
                job_id=self.config.job_id,
                subnets=subnets
            )
            
            # If no subnets were extracted, fall back to direct device discovery
            if not subnets:
                loguru_logger.warning(
                    "No subnets extracted from seed devices, falling back to direct device discovery",
                    job_id=self.config.job_id
                )
                
                # Log the transition to full pipeline discovery
                std_logger.info(f"Falling back to full pipeline discovery for job: {self.config.job_id}")
                
                # Override the method name for the full pipeline
                self.method_name = self._get_method_for_mode("full-pipeline")
                
                # Fall back to full pipeline discovery
                return await self._run_full_pipeline_discovery()
            
            # Save extracted subnets to file
            if self.config.job_id:
                write_artifact(
                    self.config.job_id,
                    "extracted_subnets.json",
                    {"subnets": subnets}
                )
            
            # Create a new config with the extracted subnets
            reachability_config = DiscoveryConfig(
                seed_devices=subnets,
                credentials=self.config.credentials,
                mode="subnet",
                job_id=self.config.job_id,
                stats=self.config.stats
            )
            
            # Create IP reachability discovery instance
            ip_reachability = IPReachabilityDiscovery(reachability_config)
            
            # Run IP reachability discovery
            result = await ip_reachability.run()
            
            # Save results to file
            if self.config.job_id:
                artifact_path = write_artifact(
                    self.config.job_id,
                    "reachability_matrix.json",
                    result.stats
                )
                
                # Add artifact path to result stats
                result.stats["artifact"] = artifact_path
            
            # Log completion
            loguru_logger.info(
                "Seed device discovery completed",
                job_id=self.config.job_id,
                total_scanned=result.stats.get("summary", {}).get("total_scanned", 0),
                icmp_reachable=result.stats.get("summary", {}).get("icmp_reachable", 0),
                ssh_open=result.stats.get("summary", {}).get("port_22_open", 0),
                https_open=result.stats.get("summary", {}).get("port_443_open", 0)
            )
            
        except Exception as e:
            std_logger.error(f"Seed device discovery error: {str(e)}")
            loguru_logger.error(f"Seed device discovery failed", job_id=self.config.job_id, error=str(e))
            result.status = "failed"
            result.stats = {"error": str(e)}
        
        finally:
            result.end_time = datetime.now()
            return result
    
    async def _run_full_pipeline_discovery(self) -> DiscoveryResult:
        """Run the full discovery pipeline."""
        # Run the discovery method
        result = await self.method.run()
        
        # Log completion
        std_logger.info(f"Discovery completed. Found {result.total_devices_found} devices.")
        loguru_logger.info(
            "Full pipeline discovery completed",
            job_id=self.config.job_id,
            total_devices=result.total_devices_found,
            successful_connections=result.successful_connections,
            failed_connections=result.failed_connections
        )
        
        return result
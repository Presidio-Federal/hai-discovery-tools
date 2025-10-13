"""
GitHub Action integration for network discovery.

This module provides a command-line interface for running network discovery
as part of a GitHub Action workflow.
"""

import os
import sys
import json
import asyncio
import argparse
import logging
from typing import Dict, List, Any

from app.models import DiscoveryConfig
from app.discovery import NetworkDiscovery, DiscoveryMethodRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='HAI Network Discovery for GitHub Actions')
    
    # Required arguments
    parser.add_argument('--seed-devices', required=True, help='Comma-separated list of seed device IPs or hostnames')
    
    # Credentials (can be provided via env vars for security)
    parser.add_argument('--credentials-file', help='Path to JSON file with credentials')
    
    # Optional arguments
    parser.add_argument('--method', default='neighbor_discovery', help='Discovery method to use')
    parser.add_argument('--max-depth', type=int, default=3, help='Maximum discovery depth')
    parser.add_argument('--protocols', default='cdp,lldp', help='Comma-separated list of discovery protocols')
    parser.add_argument('--timeout', type=int, default=60, help='Connection timeout in seconds')
    parser.add_argument('--concurrent', type=int, default=10, help='Maximum concurrent connections')
    parser.add_argument('--exclude', help='Comma-separated list of IP patterns to exclude')
    parser.add_argument('--output-file', help='Path to write discovery results JSON')
    
    return parser.parse_args()


def get_credentials(args) -> List[Dict[str, str]]:
    """Get credentials from arguments or environment variables."""
    credentials = []
    
    # Try to load from credentials file
    if args.credentials_file and os.path.exists(args.credentials_file):
        with open(args.credentials_file, 'r') as f:
            try:
                credentials = json.load(f)
                if isinstance(credentials, list):
                    return credentials
            except json.JSONDecodeError:
                logger.error(f"Error parsing credentials file: {args.credentials_file}")
    
    # Try to load from environment variables
    env_creds = os.environ.get('NETWORK_CREDENTIALS')
    if env_creds:
        try:
            creds_list = json.loads(env_creds)
            if isinstance(creds_list, list):
                return creds_list
        except json.JSONDecodeError:
            logger.error("Error parsing NETWORK_CREDENTIALS environment variable")
    
    # If no credentials found, create a default one from individual env vars
    username = os.environ.get('NETWORK_USERNAME')
    password = os.environ.get('NETWORK_PASSWORD')
    enable_secret = os.environ.get('NETWORK_ENABLE_SECRET')
    
    if username and password:
        cred = {"username": username, "password": password}
        if enable_secret:
            cred["enable_secret"] = enable_secret
        credentials.append(cred)
    
    if not credentials:
        logger.error("No credentials provided. Set credentials via file or environment variables.")
        sys.exit(1)
    
    return credentials


async def main():
    """Main entry point for GitHub Action."""
    args = parse_arguments()
    
    # Get list of available methods
    available_methods = [m["name"] for m in DiscoveryMethodRegistry.list_methods()]
    
    # Validate method
    if args.method not in available_methods:
        logger.error(f"Unknown discovery method: {args.method}")
        logger.info(f"Available methods: {', '.join(available_methods)}")
        sys.exit(1)
    
    # Parse seed devices
    seed_devices = [device.strip() for device in args.seed_devices.split(',') if device.strip()]
    if not seed_devices:
        logger.error("No seed devices provided")
        sys.exit(1)
    
    # Get credentials
    credentials = get_credentials(args)
    
    # Parse protocols
    protocols = [p.strip() for p in args.protocols.split(',') if p.strip()]
    
    # Parse exclude patterns
    exclude_patterns = []
    if args.exclude:
        exclude_patterns = [p.strip() for p in args.exclude.split(',') if p.strip()]
    
    # Create discovery configuration
    config = DiscoveryConfig(
        seed_devices=seed_devices,
        credentials=credentials,
        max_depth=args.max_depth,
        discovery_protocols=protocols,
        timeout=args.timeout,
        concurrent_connections=args.concurrent,
        exclude_patterns=exclude_patterns
    )
    
    # Initialize and run discovery
    logger.info(f"Starting discovery with method: {args.method}")
    logger.info(f"Seed devices: {', '.join(seed_devices)}")
    
    discovery = NetworkDiscovery(config, args.method)
    result = await discovery.run_discovery()
    
    # Convert to serializable format
    serialized_result = {
        "devices": {ip: device.dict() for ip, device in result.devices.items()},
        "topology": result.topology,
        "stats": {
            "total_devices": result.total_devices_found,
            "successful_connections": result.successful_connections,
            "failed_connections": result.failed_connections,
            "start_time": result.start_time.isoformat(),
            "end_time": result.end_time.isoformat() if result.end_time else None
        }
    }
    
    # Output results
    if args.output_file:
        with open(args.output_file, 'w') as f:
            json.dump(serialized_result, f, indent=2)
        logger.info(f"Results written to {args.output_file}")
    else:
        # Print summary to stdout
        print(json.dumps({
            "summary": {
                "total_devices": result.total_devices_found,
                "successful_connections": result.successful_connections,
                "failed_connections": result.failed_connections
            }
        }, indent=2))
    
    # Set GitHub Action output
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"total_devices={result.total_devices_found}\n")
            f.write(f"successful_connections={result.successful_connections}\n")
            f.write(f"failed_connections={result.failed_connections}\n")
    
    # Exit with error if no successful connections
    if result.successful_connections == 0:
        logger.error("No successful device connections")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

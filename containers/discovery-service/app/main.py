"""
Network Discovery Service API.

This module provides a FastAPI application for network discovery operations.
"""

import os
import logging
import json
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# Custom JSON encoder to handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

from app.discovery import NetworkDiscovery
from app.registry import DiscoveryMethodRegistry
from app.models import DiscoveryConfig, DiscoveryRequest
from app.exporters.topology_exporter import TopologyExporter
from app.exporters.config_exporter import ConfigExporter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title="Network Discovery Service",
    description="API for discovering network devices and extracting information",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store discovery results in memory
# In a production environment, this should be replaced with a database
discovery_results = {}

# Data directory for exports should already exist from Dockerfile
# but try to create it if it doesn't, with proper error handling
try:
    os.makedirs("/app/data/exports", exist_ok=True)
except PermissionError:
    logger.warning("Unable to create data directory due to permissions. Using existing directory.")
except Exception as e:
    logger.warning(f"Error creating data directory: {str(e)}")


@app.get("/")
def read_root():
    """API root endpoint."""
    return {
        "name": "Network Discovery Service",
        "version": "1.0.0",
        "endpoints": {
            "discover": "/discover",
            "methods": "/methods",
            "status": "/discover/{job_id}",
            "devices": "/discover/{job_id}/devices",
            "topology": "/discover/{job_id}/topology",
            "export": "/discover/{job_id}/export"
        }
    }


@app.get("/methods")
def list_methods():
    """List available discovery methods."""
    return DiscoveryMethodRegistry.list_methods()


@app.post("/discover")
async def discover(
    background_tasks: BackgroundTasks,
    request: DiscoveryRequest
):
    """
    Start a discovery operation.
    
    Request body:
    - seed_devices: List of devices or subnets to start discovery from (can include port like "ip:port")
    - credentials: List of credential sets to try
    - method: Discovery method to use ("auto" selects based on mode)
    - mode: Discovery mode ("subnet", "seed-device", or "full-pipeline")
    - max_depth: Maximum depth of discovery
    - discovery_protocols: Protocols to use for neighbor discovery
    - timeout: Connection timeout in seconds
    - concurrent_connections: Maximum number of concurrent connections
    - exclude_patterns: Patterns for IPs to exclude
    - wait_for_results: If true, wait for discovery to complete and return results directly
    - job_id: Optional custom job ID
    - probe_ports: List of TCP ports to probe for reachability
    - concurrency: Maximum number of concurrent operations for IP reachability
    
    Returns a job ID that can be used to retrieve results, or the complete results if wait_for_results is true.
    """
    # Extract values from request
    seed_devices = request.seed_devices
    credentials = request.credentials
    method = request.method
    mode = request.mode
    max_depth = request.max_depth
    discovery_protocols = request.discovery_protocols
    timeout = request.timeout
    concurrent_connections = request.concurrent_connections
    exclude_patterns = request.exclude_patterns
    wait_for_results = request.wait_for_results
    job_id = request.job_id
    probe_ports = request.probe_ports
    concurrency = request.concurrency
    
    # Validate the discovery method if not auto
    if method != "auto" and not DiscoveryMethodRegistry.get_method(method):
        raise HTTPException(status_code=400, detail=f"Unknown discovery method: {method}")
    
    # Validate the mode
    valid_modes = ["subnet", "seed-device", "full-pipeline"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Must be one of {valid_modes}")
    
    # Use the provided job ID or create a unique one
    if job_id:
        # Make sure job_id is valid and doesn't contain characters that could cause issues
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', job_id):
            raise HTTPException(status_code=400, detail="Invalid job_id. Use only alphanumeric characters, hyphens, and underscores.")
        logger.info(f"Using provided job_id: {job_id}")
    else:
        job_id = f"discovery_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(discovery_results) + 1}"
        logger.info(f"Generated job_id: {job_id}")
    
    # Create additional stats for IP reachability
    stats = {
        "probe_ports": probe_ports,
        "concurrency": concurrency
    }
    
    # Create discovery configuration
    config = DiscoveryConfig(
        seed_devices=seed_devices,
        credentials=credentials,
        max_depth=max_depth,
        discovery_protocols=discovery_protocols,
        timeout=timeout,
        concurrent_connections=concurrent_connections,
        exclude_patterns=exclude_patterns,
        mode=mode,
        job_id=job_id,
        stats=stats
    )
    
    # Store initial job status
    discovery_results[job_id] = {
        "status": "pending",
        "start_time": datetime.now().isoformat(),
        "config": config.dict(exclude={"credentials"}),  # Don't include credentials in response
        "method": method,
        "mode": mode
    }
    
    if wait_for_results:
        # Run discovery synchronously
        await run_discovery_job(job_id, config, method)
        
        # Get the result
        result = discovery_results[job_id]
        
        # Add artifact path if available
        if "result" in result and "stats" in result["result"]:
            stats = result["result"]["stats"]
            if "artifact" in stats:
                result["artifact"] = stats["artifact"]
        
        # Return complete results
        return result
    else:
        # Start discovery in background
        background_tasks.add_task(run_discovery_job, job_id, config, method)
        
        # Return job ID with endpoint info
        return {
            "job_id": job_id, 
            "status": "pending",
            "mode": mode,
            "endpoints": {
                "status": f"/discover/{job_id}",
                "devices": f"/discover/{job_id}/devices",
                "topology": f"/discover/{job_id}/topology",
                "export": f"/discover/{job_id}/export",
                "reachability": f"/discover/{job_id}/reachability"
            },
            "message": f"Discovery job started in {mode} mode. Use the endpoints above to check status and results."
        }


@app.get("/discover/{job_id}")
def get_discovery_status(job_id: str):
    """Get the status of a discovery job."""
    if job_id not in discovery_results:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = discovery_results[job_id]
    
    # Add summary information if available
    if "result" in result:
        discovery_result = result["result"]
        devices = discovery_result.get("devices", {})
        
        # Count devices by status
        status_counts = {}
        for device in devices.values():
            status = device.get("discovery_status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Add summary to result
        result["summary"] = {
            "total_devices": len(devices),
            "status_counts": status_counts
        }
        
        # Add preview of first 5 devices
        device_preview = []
        for i, (ip, device) in enumerate(devices.items()):
            if i >= 5:
                break
                
            device_preview.append({
                "ip_address": ip,
                "hostname": device.get("hostname", ""),
                "platform": device.get("platform", ""),
                "status": device.get("discovery_status", "")
            })
            
        result["device_preview"] = device_preview
        
        # Add endpoints for accessing results
        result["endpoints"] = {
            "status": f"/discover/{job_id}",
            "devices": f"/discover/{job_id}/devices",
            "topology": f"/discover/{job_id}/topology",
            "export": f"/discover/{job_id}/export"
        }
    
    return result


@app.get("/discover/{job_id}/devices")
def get_discovery_devices(
    job_id: str,
    status: Optional[str] = None,
    include_config: bool = False
):
    """
    Get devices discovered in a job.
    
    Parameters:
    - job_id: The job ID
    - status: Filter devices by status (discovered, failed, unreachable)
    - include_config: Whether to include device configurations in the response
    """
    if job_id not in discovery_results:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = discovery_results[job_id]
    
    if "result" not in result or result["status"] == "pending":
        return {"status": "pending", "message": "Discovery is still in progress"}
    
    devices = result["result"].get("devices", {})
    
    # Filter by status if specified
    if status:
        devices = {
            ip: device for ip, device in devices.items() 
            if device.get("discovery_status") == status
        }
    
    # Remove configuration if not requested
    if not include_config:
        for device in devices.values():
            device.pop("config", None)
    
    return {"devices": devices}


@app.get("/discover/{job_id}/topology", response_class=HTMLResponse)
def get_discovery_topology(job_id: str, debug: bool = False):
    """
    Get network topology visualization for a job.
    
    Returns an HTML page with interactive network visualization.
    
    Parameters:
    - job_id: The job ID
    - debug: If true, returns detailed error information in the response
    """
    if job_id not in discovery_results:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = discovery_results[job_id]
    
    if "result" not in result or result["status"] == "pending":
        return HTMLResponse(content="<html><body><h1>Discovery in progress</h1><p>Please check back later.</p></body></html>")
    
    try:
        # Create topology data
        devices = result["result"].get("devices", {})
        connections = result["result"].get("connections", [])
        
        # Log what we're working with
        logger.info(f"Job {job_id} has {len(devices)} devices and {len(connections)} connections")
        
        # Check if we have any data to visualize
        if not devices:
            error_msg = "No devices found in discovery results"
            logger.error(error_msg)
            return HTMLResponse(content=f"<html><body><h1>No topology data</h1><p>{error_msg}</p></body></html>")
        
        topology_data = {
            "devices": devices,
            "connections": connections
        }
        
        # Export to HTML
        try:
            # Ensure directory exists
            os.makedirs("/app/data/exports", exist_ok=True)
        except Exception as e:
            logger.warning(f"Error creating exports directory: {str(e)}")
            
        export_file = f"/app/data/exports/{job_id}_topology.html"
        logger.info(f"Exporting topology to {export_file}")
        
        # Try to export the topology
        export_result = TopologyExporter.export_to_html(topology_data, export_file)
        if not export_result:
            error_msg = f"Failed to export topology to HTML for job {job_id}"
            logger.error(error_msg)
            if debug:
                # Return more detailed error info if debug mode
                return HTMLResponse(content=f"<html><body><h1>Error generating topology</h1><p>{error_msg}</p><pre>Devices: {len(devices)}\nConnections: {len(connections)}\nExport file: {export_file}</pre></body></html>")
            else:
                return HTMLResponse(content=f"<html><body><h1>Error generating topology</h1><p>{error_msg}</p><p>Add '?debug=true' to the URL for more details.</p></body></html>")
        
        # Read the HTML file
        try:
            with open(export_file, 'r') as f:
                html_content = f.read()
            
            return HTMLResponse(content=html_content)
        except Exception as e:
            error_msg = f"Error reading topology HTML file: {str(e)}"
            logger.error(error_msg)
            if debug:
                return HTMLResponse(content=f"<html><body><h1>Error reading topology</h1><p>{error_msg}</p><pre>File path: {export_file}</pre></body></html>")
            else:
                return HTMLResponse(content=f"<html><body><h1>Error reading topology</h1><p>{error_msg}</p><p>Add '?debug=true' to the URL for more details.</p></body></html>")
    except Exception as e:
        error_msg = f"Error generating topology visualization: {str(e)}"
        logger.error(error_msg)
        import traceback
        tb = traceback.format_exc()
        logger.error(tb)
        if debug:
            return HTMLResponse(content=f"<html><body><h1>Error generating topology</h1><p>{error_msg}</p><pre>{tb}</pre></body></html>")
        else:
            return HTMLResponse(content=f"<html><body><h1>Error generating topology</h1><p>{error_msg}</p><p>Add '?debug=true' to the URL for more details.</p></body></html>")


@app.get("/discover/{job_id}/export")
def export_discovery_data(
    job_id: str,
    format: str = "json",
    include_configs: bool = True
):
    """
    Export discovery data in various formats.
    
    Parameters:
    - job_id: The job ID
    - format: Export format (json, csv, html)
    - include_configs: Whether to include device configurations in the export
    
    Returns a file download.
    """
    if job_id not in discovery_results:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = discovery_results[job_id]
    
    if "result" not in result or result["status"] == "pending":
        return {"status": "pending", "message": "Discovery is still in progress"}
    
    # Create export directory
    export_dir = f"/app/data/exports/{job_id}"
    try:
        os.makedirs(export_dir, exist_ok=True)
    except PermissionError:
        logger.warning(f"Permission denied creating directory {export_dir}")
        export_dir = "/app/data/exports"
    
    # Export based on format
    if format == "json":
        # Export to JSON
        export_file = f"{export_dir}/discovery_data.json"
        with open(export_file, 'w') as f:
            json.dump(result["result"], f, indent=2, cls=DateTimeEncoder)
        
        # Always return as attachment for download
        return FileResponse(
            path=export_file,
            filename=f"discovery_{job_id}.json",
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=discovery_{job_id}.json"}
        )
        
    # CSV format has been removed in favor of JSON
    # This section is kept as a placeholder for backward compatibility
    elif format == "csv":
        # Export device inventory as JSON instead
        devices = result["result"].get("devices", {})
        inventory_file = f"{export_dir}/device_inventory.json"
        
        # Generate the JSON file
        ConfigExporter.export_inventory_json(devices, inventory_file)
        
        # Return the file as an attachment
        return FileResponse(
            path=inventory_file,
            filename=f"device_inventory_{job_id}.json",
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=device_inventory_{job_id}.json"}
        )
        
    elif format == "html":
        # Export topology to HTML
        topology_data = {
            "devices": result["result"].get("devices", {}),
            "connections": result["result"].get("connections", [])
        }
        
        export_file = f"{export_dir}/topology.html"
        TopologyExporter.export_to_html(topology_data, export_file)
        
        return FileResponse(
            path=export_file,
            filename=f"topology_{job_id}.html",
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=topology_{job_id}.html"}
        )
        
    elif format == "configs":
        # Export raw configs
        if include_configs:
            devices = result["result"].get("devices", {})
            config_dir = f"{export_dir}/configs"
            
            # Create a zip file with all configs
            zip_file = f"{export_dir}/configs_{job_id}.zip"
            
            # Ensure the configs directory exists
            try:
                os.makedirs(config_dir, exist_ok=True)
            except Exception as e:
                logger.warning(f"Error creating config directory: {str(e)}")
            
            # Export configs to directory
            ConfigExporter.export_raw_configs(devices, config_dir)
            
            # Create a zip file of the configs
            import zipfile
            try:
                with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(config_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, os.path.relpath(file_path, config_dir))
                
                # Return the zip file as an attachment
                return FileResponse(
                    path=zip_file,
                    filename=f"configs_{job_id}.zip",
                    media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=configs_{job_id}.zip"}
                )
            except Exception as e:
                logger.error(f"Error creating zip file: {str(e)}")
                return {"status": "error", "message": f"Error creating zip file: {str(e)}"}
        else:
            return {"status": "error", "message": "Configs not included in export"}
            
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {format}")


@app.get("/discover/{job_id}/export/device_inventory")
def export_device_inventory(job_id: str):
    """Export device inventory to JSON."""
    export_file = f"/app/data/exports/{job_id}/device_inventory.json"
    
    if not os.path.exists(export_file):
        # Try to generate the file if it doesn't exist
        if job_id in discovery_results and "result" in discovery_results[job_id]:
            result = discovery_results[job_id]
            devices = result["result"].get("devices", {})
            
            # Create export directory
            export_dir = f"/app/data/exports/{job_id}"
            try:
                os.makedirs(export_dir, exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory {export_dir}")
                export_dir = "/app/data/exports"
                export_file = f"{export_dir}/device_inventory_{job_id}.json"
            
            # Generate the JSON file
            ConfigExporter.export_inventory_json(devices, export_file)
        else:
            raise HTTPException(status_code=404, detail="Export file not found and job data unavailable")
    
    return FileResponse(
        path=export_file,
        filename=f"device_inventory_{job_id}.json",
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=device_inventory_{job_id}.json"}
    )


@app.get("/discover/{job_id}/export/interface_inventory")
def export_interface_inventory(job_id: str):
    """Export interface inventory to JSON."""
    export_file = f"/app/data/exports/{job_id}/interface_inventory.json"
    
    if not os.path.exists(export_file):
        # Try to generate the file if it doesn't exist
        if job_id in discovery_results and "result" in discovery_results[job_id]:
            result = discovery_results[job_id]
            devices = result["result"].get("devices", {})
            
            # Create export directory
            export_dir = f"/app/data/exports/{job_id}"
            try:
                os.makedirs(export_dir, exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory {export_dir}")
                export_dir = "/app/data/exports"
                export_file = f"{export_dir}/interface_inventory_{job_id}.json"
            
            # Generate the JSON file
            ConfigExporter.export_interface_json(devices, export_file)
        else:
            raise HTTPException(status_code=404, detail="Export file not found and job data unavailable")
    
    return FileResponse(
        path=export_file,
        filename=f"interface_inventory_{job_id}.json",
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=interface_inventory_{job_id}.json"}
    )


@app.get("/discover/{job_id}/reachability")
def get_reachability_results(job_id: str):
    """Get reachability results for a discovery job."""
    logger.info(f"Getting reachability results for job: {job_id}")
    
    # Check multiple possible locations for the reachability data
    possible_paths = [
        f"/app/data/exports/{job_id}/reachability_matrix.json",  # Standard path
        f"/app/data/discovery/{job_id}/reachability_matrix.json",  # Alternative path used by some modules
        f"/app/data/exports/reachability_matrix.json",  # Fallback path
        f"/app/data/exports/{job_id}/discovery_data.json"  # Full discovery data
    ]
    
    # Try each path
    for path in possible_paths:
        logger.info(f"Checking for reachability data at: {path}")
        if os.path.exists(path):
            logger.info(f"Found data at: {path}")
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    
                    # If this is the discovery_data.json file, extract the relevant reachability info
                    if path.endswith("discovery_data.json"):
                        # Create a reachability matrix from the discovered devices
                        devices = data.get("devices", {})
                        reachability_data = {
                            "results": [],
                            "summary": {
                                "total_scanned": len(devices),
                                "reachable": len([d for d in devices.values() if d.get("discovery_status") == "discovered"]),
                                "unreachable": len([d for d in devices.values() if d.get("discovery_status") == "failed"])
                            },
                            "timestamp": data.get("start_time", datetime.now().isoformat()),
                            "duration_sec": 0
                        }
                        
                        # Add each device to the results
                        for ip, device in devices.items():
                            status = device.get("discovery_status", "unknown")
                            open_ports = []
                            
                            # If we successfully connected, add port 22 as open
                            if status == "discovered" and device.get("credentials_used", {}).get("port") == "22":
                                open_ports.append(22)
                            
                            reachability_data["results"].append({
                                "ip": ip,
                                "icmp_responsive": status == "discovered",
                                "open_ports": open_ports
                            })
                            
                        # Save this reachability data for future use
                        try:
                            export_dir = f"/app/data/exports/{job_id}"
                            os.makedirs(export_dir, exist_ok=True)
                            reachability_file = f"{export_dir}/reachability_matrix.json"
                            with open(reachability_file, 'w') as f:
                                json.dump(reachability_data, f, indent=2, cls=DateTimeEncoder)
                            logger.info(f"Saved extracted reachability data to: {reachability_file}")
                        except Exception as e:
                            logger.warning(f"Error saving reachability data to file: {str(e)}")
                            
                        return reachability_data
                    else:
                        return data
            except Exception as e:
                logger.error(f"Error reading data from {path}: {str(e)}")
    
    # If file doesn't exist, check if we have reachability data in the job results
    if job_id in discovery_results:
        logger.info(f"Checking in-memory results for job: {job_id}")
        result = discovery_results[job_id]
        
        # Check if this was a reachability scan
        if result.get("mode") in ["subnet", "seed-device", "full-pipeline"]:
            # Extract reachability data from the result
            if "result" in result and "stats" in result["result"]:
                stats = result["result"]["stats"]
                
                # Look for reachability data in various formats
                if "results" in stats:
                    logger.info(f"Found reachability data in memory for job: {job_id}")
                    
                    # Save the data to a file for future requests
                    try:
                        export_dir = f"/app/data/exports/{job_id}"
                        os.makedirs(export_dir, exist_ok=True)
                        reachability_file = f"{export_dir}/reachability_matrix.json"
                        with open(reachability_file, 'w') as f:
                            json.dump(stats, f, indent=2, cls=DateTimeEncoder)
                        logger.info(f"Saved reachability data to: {reachability_file}")
                    except Exception as e:
                        logger.warning(f"Error saving reachability data to file: {str(e)}")
                    
                    return stats
        
        # If we have devices, create reachability data from them
        if "result" in result and "devices" in result["result"]:
            devices = result["result"]["devices"]
            reachability_data = {
                "results": [],
                "summary": {
                    "total_scanned": len(devices),
                    "reachable": len([d for d in devices.values() if d.get("discovery_status") == "discovered"]),
                    "unreachable": len([d for d in devices.values() if d.get("discovery_status") == "failed"])
                },
                "timestamp": result.get("start_time", datetime.now().isoformat()),
                "duration_sec": 0
            }
            
            # Add each device to the results
            for ip, device in devices.items():
                status = device.get("discovery_status", "unknown")
                open_ports = []
                
                # If we successfully connected, add port 22 as open
                if status == "discovered" and device.get("credentials_used", {}).get("port") == "22":
                    open_ports.append(22)
                
                reachability_data["results"].append({
                    "ip": ip,
                    "icmp_responsive": status == "discovered",
                    "open_ports": open_ports
                })
                
            # Save this reachability data for future use
            try:
                export_dir = f"/app/data/exports/{job_id}"
                os.makedirs(export_dir, exist_ok=True)
                reachability_file = f"{export_dir}/reachability_matrix.json"
                with open(reachability_file, 'w') as f:
                    json.dump(reachability_data, f, indent=2, cls=DateTimeEncoder)
                logger.info(f"Saved generated reachability data to: {reachability_file}")
            except Exception as e:
                logger.warning(f"Error saving reachability data to file: {str(e)}")
                
            return reachability_data
    
    # If we couldn't find reachability data
    logger.warning(f"Reachability data not found for job: {job_id}")
    raise HTTPException(status_code=404, detail="Reachability data not found for this job")


async def run_discovery_job(job_id: str, config: DiscoveryConfig, method: str):
    """Run a discovery job in the background."""
    try:
        # Update job status
        discovery_results[job_id]["status"] = "running"
        
        # Create discovery instance
        discovery = NetworkDiscovery(config, method)
        
        # Run discovery
        result = await discovery.run_discovery()
        
        # Generate export files based on the mode
        export_dir = f"/app/data/exports/{job_id}"
        try:
            os.makedirs(export_dir, exist_ok=True)
            
            # For subnet or seed-device mode, export reachability data
            if config.mode in ["subnet", "seed-device"] and result.stats:
                # Save reachability matrix
                from app.utils import write_artifact
                artifact_path = write_artifact(job_id, "reachability_matrix.json", result.stats)
                result.stats["artifact"] = artifact_path
            
            # For full-pipeline mode, export all data
            if config.mode == "full-pipeline":
                # Export device inventory as JSON
                ConfigExporter.export_inventory_json(
                    result.devices, 
                    f"{export_dir}/device_inventory.json"
                )
                
                # Export interface inventory as JSON
                ConfigExporter.export_interface_json(
                    result.devices, 
                    f"{export_dir}/interface_inventory.json"
                )
                
                # Export topology as JSON
                topology_data = {
                    "devices": result.devices,
                    "connections": result.connections
                }
                TopologyExporter.export_to_json(
                    topology_data, 
                    f"{export_dir}/topology.json"
                )
                
                # Export topology as HTML
                TopologyExporter.export_to_html(
                    topology_data, 
                    f"{export_dir}/topology.html"
                )
                
                # Export configs
                ConfigExporter.export_raw_configs(
                    result.devices, 
                    f"{export_dir}/configs"
                )
        except Exception as e:
            logger.error(f"Error generating export files: {str(e)}")
        
        # Update job status with result
        discovery_results[job_id].update({
            "status": "completed",
            "end_time": datetime.now().isoformat(),
            "result": result.dict(exclude_none=True)  # Exclude None values to avoid serialization issues
        })
        
        # Log completion
        if config.mode == "subnet":
            # For subnet mode, only report on the reachability scan
            summary = result.stats.get("summary", {})
            
            # Check for attempted_hosts which is more accurate than total_scanned
            total_scanned = summary.get('attempted_hosts', summary.get('total_scanned', 0))
            
            # If we still don't have a count, try to get it from the results
            if total_scanned == 0 and 'results' in result.stats:
                total_scanned = len(result.stats.get('results', []))
            
            logger.info(
                f"Job {job_id} completed successfully. "
                f"Scanned {total_scanned} hosts, "
                f"found {summary.get('icmp_reachable', 0)} reachable via ICMP, "
                f"{summary.get('port_22_open', 0)} with SSH open."
            )
        elif config.mode == "seed-device":
            # For seed-device mode, report both on devices found and hosts scanned
            summary = result.stats.get("summary", {})
            
            # Check for attempted_hosts which is more accurate than total_scanned
            total_scanned = summary.get('attempted_hosts', summary.get('total_scanned', 0))
            
            # If we still don't have a count, try to get it from the results
            if total_scanned == 0 and 'results' in result.stats:
                total_scanned = len(result.stats.get('results', []))
                
            # Get device counts
            total_devices = result.total_devices_found
            successful_devices = result.successful_connections
            
            logger.info(
                f"Job {job_id} completed successfully. "
                f"Found {total_devices} devices ({successful_devices} successful connections). "
                f"Scanned {total_scanned} hosts, "
                f"found {summary.get('icmp_reachable', 0)} reachable via ICMP, "
                f"{summary.get('port_22_open', 0)} with SSH open."
            )
        else:
            # For full-pipeline mode - also include scan count from stats if available
            summary = result.stats.get("summary", {})
            total_devices = result.total_devices_found
            successful_devices = result.successful_connections
            
            # Check for attempted_hosts which is more accurate than total_scanned
            total_scanned = summary.get('attempted_hosts', summary.get('total_scanned', 0))
            
            # If we still don't have a count, try to get it from the results
            if total_scanned == 0 and 'results' in result.stats:
                total_scanned = len(result.stats.get('results', []))
                
            # Count SSH connections attempted as a fallback
            if total_scanned == 0:
                # At minimum, we tried to connect to each device
                total_scanned = result.total_devices_found + result.failed_connections
                
            logger.info(
                f"Job {job_id} completed successfully. "
                f"Found {total_devices} devices ({successful_devices} successful connections). "
                f"Scanned {total_scanned} hosts."
            )
        
    except Exception as e:
        logger.error(f"Error running discovery job {job_id}: {str(e)}")
        import traceback
        logger.error(f"Job error traceback: {traceback.format_exc()}")
        
        # Update job status with error
        discovery_results[job_id].update({
            "status": "failed",
            "end_time": datetime.now().isoformat(),
            "error": str(e)
        })
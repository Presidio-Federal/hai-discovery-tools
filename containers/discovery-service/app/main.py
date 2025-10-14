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
from app.models import DiscoveryConfig
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
    seed_devices: List[str],
    credentials: List[Dict[str, str]],
    method: str = "neighbor_discovery",
    max_depth: int = 3,
    discovery_protocols: List[str] = ["cdp", "lldp"],
    timeout: int = 60,
    concurrent_connections: int = 10,
    exclude_patterns: List[str] = [],
    wait_for_results: bool = False
):
    """
    Start a discovery operation.
    
    Parameters:
    - seed_devices: List of devices to start discovery from (can include port like "ip:port")
    - credentials: List of credential sets to try
    - method: Discovery method to use
    - max_depth: Maximum depth of discovery
    - discovery_protocols: Protocols to use for neighbor discovery
    - timeout: Connection timeout in seconds
    - concurrent_connections: Maximum number of concurrent connections
    - exclude_patterns: Patterns for IPs to exclude
    - wait_for_results: If true, wait for discovery to complete and return results directly
    
    Returns a job ID that can be used to retrieve results, or the complete results if wait_for_results is true.
    """
    # Validate the discovery method
    if not DiscoveryMethodRegistry.get_method(method):
        raise HTTPException(status_code=400, detail=f"Unknown discovery method: {method}")
    
    # Create a unique job ID
    job_id = f"discovery_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(discovery_results) + 1}"
    
    # Create discovery configuration
    config = DiscoveryConfig(
        seed_devices=seed_devices,
        credentials=credentials,
        max_depth=max_depth,
        discovery_protocols=discovery_protocols,
        timeout=timeout,
        concurrent_connections=concurrent_connections,
        exclude_patterns=exclude_patterns
    )
    
    # Store initial job status
    discovery_results[job_id] = {
        "status": "pending",
        "start_time": datetime.now().isoformat(),
        "config": config.dict(exclude={"credentials"}),  # Don't include credentials in response
        "method": method
    }
    
    if wait_for_results:
        # Run discovery synchronously
        await run_discovery_job(job_id, config, method)
        # Return complete results
        return discovery_results[job_id]
    else:
        # Start discovery in background
        background_tasks.add_task(run_discovery_job, job_id, config, method)
        
        # Return job ID with endpoint info
        return {
            "job_id": job_id, 
            "status": "pending",
            "endpoints": {
                "status": f"/discover/{job_id}",
                "devices": f"/discover/{job_id}/devices",
                "topology": f"/discover/{job_id}/topology",
                "export": f"/discover/{job_id}/export"
            },
            "message": "Discovery job started. Use the endpoints above to check status and results."
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
        
    elif format == "csv":
        # Export device inventory to CSV
        devices = result["result"].get("devices", {})
        inventory_file = f"{export_dir}/device_inventory.csv"
        
        # Generate the CSV file
        ConfigExporter.export_inventory_report(devices, inventory_file)
        
        # Return the file as an attachment
        return FileResponse(
            path=inventory_file,
            filename=f"device_inventory_{job_id}.csv",
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=device_inventory_{job_id}.csv"}
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
    """Export device inventory to CSV."""
    export_file = f"/app/data/exports/{job_id}/device_inventory.csv"
    
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
                export_file = f"{export_dir}/device_inventory_{job_id}.csv"
            
            # Generate the CSV file
            ConfigExporter.export_inventory_report(devices, export_file)
        else:
            raise HTTPException(status_code=404, detail="Export file not found and job data unavailable")
    
    return FileResponse(
        path=export_file,
        filename=f"device_inventory_{job_id}.csv",
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=device_inventory_{job_id}.csv"}
    )


@app.get("/discover/{job_id}/export/interface_inventory")
def export_interface_inventory(job_id: str):
    """Export interface inventory to CSV."""
    export_file = f"/app/data/exports/{job_id}/interface_inventory.csv"
    
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
                export_file = f"{export_dir}/interface_inventory_{job_id}.csv"
            
            # Generate the CSV file
            ConfigExporter.export_interface_report(devices, export_file)
        else:
            raise HTTPException(status_code=404, detail="Export file not found and job data unavailable")
    
    return FileResponse(
        path=export_file,
        filename=f"interface_inventory_{job_id}.csv",
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=interface_inventory_{job_id}.csv"}
    )


async def run_discovery_job(job_id: str, config: DiscoveryConfig, method: str):
    """Run a discovery job in the background."""
    try:
        # Update job status
        discovery_results[job_id]["status"] = "running"
        
        # Create discovery instance
        discovery = NetworkDiscovery(config, method)
        
        # Run discovery
        result = await discovery.run_discovery()
        
        # Update job status with result
        discovery_results[job_id].update({
            "status": "completed",
            "end_time": datetime.now().isoformat(),
            "result": result.dict(exclude_none=True)  # Exclude None values to avoid serialization issues
        })
        
        # Log completion
        logger.info(f"Job {job_id} completed successfully. Found {result.total_devices_found} devices.")
        
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
"""
Topology exporter for network discovery.

This module provides functions to export network topology in various formats.
"""

import json
import logging
from typing import Dict, List, Any, Optional
import os
from datetime import datetime, date

logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


class TopologyExporter:
    """Exporter for network topology data."""
    
    @staticmethod
    def export_to_json(topology_data: Dict[str, Any], output_file: str) -> bool:
        """
        Export topology data to a JSON file.
        
        Args:
            topology_data: The topology data to export
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_file.startswith("/app/data/"):
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
            
            # Create directory if it doesn't exist
            try:
                os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory for {output_file}")
                # Try to use a directory we know exists
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
            
            # Write JSON file with custom encoder for datetime objects
            with open(output_file, 'w') as f:
                json.dump(topology_data, f, indent=2, cls=DateTimeEncoder)
                
            return True
            
        except Exception as e:
            logger.error(f"Error exporting topology to JSON: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    @staticmethod
    def export_to_dot(topology_data: Dict[str, Any], output_file: str) -> bool:
        """
        Export topology data to a DOT file for visualization with Graphviz.
        
        Args:
            topology_data: The topology data to export
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Make sure we're using the /app/data directory
            if not output_file.startswith("/app/data/"):
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
                
            # Create directory if it doesn't exist
            try:
                os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            except PermissionError:
                logger.warning(f"Permission denied creating directory for {output_file}")
                # Try to use a directory we know exists
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
            
            # Generate DOT file content
            dot_content = "digraph network {\n"
            dot_content += "  rankdir=LR;\n"
            dot_content += "  node [shape=box, style=filled, fillcolor=lightblue];\n\n"
            
            # Add nodes
            devices = topology_data.get("devices", {})
            for ip, device in devices.items():
                hostname = device.get("hostname", ip)
                platform = device.get("platform", "unknown")
                label = f"{hostname}\\n{ip}\\n{platform}"
                
                # Set node color based on device status
                color = "lightblue"
                if device.get("discovery_status") == "failed":
                    color = "lightcoral"
                elif device.get("discovery_status") == "unreachable":
                    color = "lightgrey"
                
                dot_content += f"  \"{ip}\" [label=\"{label}\", fillcolor=\"{color}\"];\n"
            
            # Add edges
            dot_content += "\n"
            
            connections = topology_data.get("connections", [])
            for conn in connections:
                source = conn.get("source")
                target = conn.get("target")
                source_port = conn.get("source_port", "")
                target_port = conn.get("target_port", "")
                
                if source and target:
                    label = f"{source_port} - {target_port}"
                    dot_content += f"  \"{source}\" -> \"{target}\" [label=\"{label}\", dir=none];\n"
            
            dot_content += "}\n"
            
            # Write DOT file
            with open(output_file, 'w') as f:
                f.write(dot_content)
                
            return True
            
        except Exception as e:
            logger.error(f"Error exporting topology to DOT: {str(e)}")
            return False
    
    @staticmethod
    def export_to_html(topology_data: Dict[str, Any], output_file: str) -> bool:
        """
        Export topology data to an HTML file with interactive visualization.
        
        Args:
            topology_data: The topology data to export
            output_file: The path to the output file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Log what we're working with
            devices = topology_data.get("devices", {})
            connections = topology_data.get("connections", [])
            logger.info(f"Exporting topology with {len(devices)} devices and {len(connections)} connections")
            
            # Validate input data
            if not devices:
                logger.error("No devices in topology data, cannot generate visualization")
                return False
                
            # Make sure we're using the /app/data directory
            if not output_file.startswith("/app/data/"):
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
                
            # Create directory if it doesn't exist
            try:
                parent_dir = os.path.dirname(os.path.abspath(output_file))
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                    logger.info(f"Created directory: {parent_dir}")
            except PermissionError:
                logger.warning(f"Permission denied creating directory for {output_file}")
                # Try to use a directory we know exists
                output_file = f"/app/data/exports/{os.path.basename(output_file)}"
                logger.info(f"Using fallback path: {output_file}")
                
            # Log device details for debugging
            for ip, device in devices.items():
                logger.debug(f"Device: {ip}, hostname: {device.get('hostname', 'unknown')}, type: {device.get('device_type', 'unknown')}")
                
            # Log connection details for debugging
            for i, conn in enumerate(connections):
                logger.debug(f"Connection {i}: {conn.get('source', 'unknown')} -> {conn.get('target', 'unknown')}")
            
            # Generate HTML content with D3.js
            # Clean up the data before sending it to the browser
            cleaned_data = {
                "devices": {},
                "connections": topology_data.get("connections", [])
            }
            
            # Process and clean devices
            for ip, device in topology_data.get("devices", {}).items():
                cleaned_device = {
                    "hostname": device.get("hostname", ip),
                    "ip_address": ip,
                    "platform": device.get("platform", "unknown"),
                    "device_type": device.get("device_type", "unknown"),
                    "discovery_status": device.get("discovery_status", "unknown"),
                    "interfaces": device.get("interfaces", [])
                }
                
                # Don't include the full config in the visualization data
                if "config" in device:
                    del device["config"]
                if "parsed_config" in device:
                    del device["parsed_config"]
                    
                cleaned_data["devices"][ip] = cleaned_device
            
            html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Network Topology</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        #topology { width: 100%; height: 800px; border: 1px solid #ddd; }
        .node { cursor: pointer; }
        .link { stroke: #999; stroke-opacity: 0.6; stroke-width: 2px; }
        .node text { font-size: 12px; font-weight: bold; }
        .tooltip { 
            position: absolute; 
            background: white; 
            border: 1px solid #ddd; 
            border-radius: 4px; 
            padding: 10px; 
            pointer-events: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .legend {
            position: absolute;
            top: 20px;
            right: 20px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .legend-item {
            display: flex;
            align-items: center;
            margin-bottom: 5px;
        }
        .legend-color {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 10px;
        }
        h1 { margin-top: 0; }
    </style>
</head>
<body>
    <h1>Network Topology Visualization</h1>
    <div id="topology"></div>
    <div class="legend">
        <h3>Legend</h3>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #69b3a2;"></div>
            <div>Discovered</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #ff7f7f;"></div>
            <div>Failed</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #cccccc;"></div>
            <div>Unreachable</div>
        </div>
    </div>
    <script>
        // Topology data
        const data = """ + json.dumps(cleaned_data, cls=DateTimeEncoder) + """;
        
        // Create nodes and links for D3
        const nodes = [];
        const links = [];
        
        // Add nodes
        for (const [ip, device] of Object.entries(data.devices)) {
            const hostname = device.hostname || ip;
            // Clean up hostname if it contains error message
            const cleanHostname = hostname.startsWith('^') ? 
                (device.platform || device.device_type || 'Unknown Device') : hostname;
            const status = device.discovery_status || 'unknown';
            
            nodes.push({
                id: ip,
                hostname: cleanHostname,
                ip: ip,
                platform: device.platform || 'unknown',
                device_type: device.device_type || 'unknown',
                status: status,
                interfaces: device.interfaces || []
            });
        }
        
        // Add links
        for (const conn of (data.connections || [])) {
            if (conn.source && conn.target) {
                links.push({
                    source: conn.source,
                    target: conn.target,
                    sourcePort: conn.source_port || '',
                    targetPort: conn.target_port || ''
                });
            }
        }
        
        // Create D3 force simulation
        const width = window.innerWidth - 40; // Account for padding
        const height = 800;
        
        // Add debug information at the top of the visualization
        d3.select("#topology").append("div")
            .style("margin-bottom", "20px")
            .style("padding", "10px")
            .style("background-color", "#f8f9fa")
            .style("border", "1px solid #ddd")
            .style("border-radius", "4px")
            .html(`
                <h3 style="margin-top:0">Visualization Debug Info</h3>
                <p><strong>Nodes found:</strong> ${nodes.length} (should see ${Object.keys(data.devices).length} devices)</p>
                <p><strong>Links found:</strong> ${links.length} (should see ${data.connections.length} connections)</p>
                <p><strong>Device IPs:</strong> ${nodes.map(n => n.id).join(', ')}</p>
                <details>
                    <summary>View node data</summary>
                    <pre style="max-height:200px;overflow:auto">${JSON.stringify(nodes, null, 2)}</pre>
                </details>
            `);
            
        // Initialize force simulation with stronger forces to ensure visibility
        const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-800))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .alphaDecay(0.01) // Slower cooling for better layout
        
        const svg = d3.select("#topology")
            .append("svg")
            .attr("width", "100%")
            .attr("height", height)
            .attr("viewBox", [0, 0, width, height]);
        
        // Add zoom functionality
        const g = svg.append("g");
        svg.call(d3.zoom()
            .extent([[0, 0], [width, height]])
            .scaleExtent([0.1, 8])
            .on("zoom", (event) => {
                g.attr("transform", event.transform);
            }));
            
        // Define device icons
        const defs = svg.append("defs");
        
        // Router icon
        defs.append("svg:symbol")
            .attr("id", "router")
            .attr("viewBox", "0 0 100 100")
            .append("svg:path")
            .attr("d", "M20,20 L80,20 L80,80 L20,80 Z M10,50 L20,50 M80,50 L90,50 M50,10 L50,20 M50,80 L50,90")
            .attr("stroke", "black")
            .attr("stroke-width", "5")
            .attr("fill", "none");
            
        // Switch icon
        defs.append("svg:symbol")
            .attr("id", "switch")
            .attr("viewBox", "0 0 100 100")
            .append("svg:path")
            .attr("d", "M20,20 L80,20 L80,80 L20,80 Z M10,30 L20,30 M10,50 L20,50 M10,70 L20,70 M80,30 L90,30 M80,50 L90,50 M80,70 L90,70")
            .attr("stroke", "black")
            .attr("stroke-width", "5")
            .attr("fill", "none");
            
        // Generic device icon
        defs.append("svg:symbol")
            .attr("id", "device")
            .attr("viewBox", "0 0 100 100")
            .append("svg:path")
            .attr("d", "M20,20 L80,20 L80,80 L20,80 Z")
            .attr("stroke", "black")
            .attr("stroke-width", "5")
            .attr("fill", "none");
        
        // Create links with stronger visibility
        const link = g.append("g")
            .selectAll("line")
            .data(links)
            .enter()
            .append("line")
            .attr("class", "link")
            .attr("stroke", "#333")
            .attr("stroke-width", 2);
        
        // Create link labels with better visibility
        const linkText = g.append("g")
            .selectAll("text")
            .data(links)
            .enter()
            .append("text")
            .attr("font-size", "10px")
            .attr("font-weight", "bold")
            .attr("text-anchor", "middle")
            .attr("dy", -5)
            .attr("fill", "#333")
            .each(function() {
                // Add white background to text for better readability
                const text = d3.select(this);
                const parent = d3.select(this.parentNode);
                
                parent.append("rect")
                    .attr("width", function() { 
                        return text.node().getBBox().width + 6; 
                    })
                    .attr("height", function() { 
                        return text.node().getBBox().height + 4; 
                    })
                    .attr("x", function() { 
                        return text.node().getBBox().x - 3; 
                    })
                    .attr("y", function() { 
                        return text.node().getBBox().y - 2; 
                    })
                    .attr("fill", "white")
                    .attr("stroke", "none")
                    .lower(); // Put rectangle behind text
            })
            .text(d => `${d.sourcePort} - ${d.targetPort}`);
        
        // Create nodes
        const node = g.append("g")
            .selectAll("g")
            .data(nodes)
            .enter()
            .append("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));
        
        // Background for nodes
        node.append("circle")
            .attr("r", 25)
            .attr("stroke", "#333")
            .attr("stroke-width", 2)
            .attr("fill", d => {
                if (d.status === 'discovered') return "#69b3a2";
                if (d.status === 'failed') return "#ff7f7f";
                if (d.status === 'unreachable') return "#cccccc";
                return "#b8b8b8";
            });
            
        // Device icons
        node.append("use")
            .attr("xlink:href", d => {
                const type = (d.device_type || "").toLowerCase();
                if (type.includes('router') || type.includes('ios') || type.includes('xe') || type.includes('xr')) {
                    return "#router";
                } else if (type.includes('switch') || type.includes('nxos') || type.includes('eos')) {
                    return "#switch";
                } else {
                    return "#device";
                }
            })
            .attr("width", 30)
            .attr("height", 30)
            .attr("x", -15)
            .attr("y", -15);
        
        // Node labels
        node.append("text")
            .attr("dy", 40)
            .attr("text-anchor", "middle")
            .text(d => d.hostname);
        
        // Tooltip
        const tooltip = d3.select("body")
            .append("div")
            .attr("class", "tooltip")
            .style("opacity", 0);
        
        node.on("mouseover", function(event, d) {
            tooltip.transition()
                .duration(200)
                .style("opacity", .9);
                
            let interfaceList = '';
            if (d.interfaces && d.interfaces.length > 0) {
                interfaceList = '<h4>Interfaces:</h4><ul>';
                d.interfaces.forEach(intf => {
                    interfaceList += `<li>${intf.name}${intf.ip_address ? ' - ' + intf.ip_address : ''}</li>`;
                });
                interfaceList += '</ul>';
            }
            
            // Build neighbor list if available
            let neighborList = '';
            const deviceNeighbors = [];
            data.connections.forEach(conn => {
                if (conn.source === d.id) {
                    const targetDevice = data.devices[conn.target];
                    if (targetDevice) {
                        const targetName = targetDevice.hostname || conn.target;
                        deviceNeighbors.push({
                            name: targetName,
                            local_port: conn.source_port,
                            remote_port: conn.target_port
                        });
                    }
                } else if (conn.target === d.id) {
                    const sourceDevice = data.devices[conn.source];
                    if (sourceDevice) {
                        const sourceName = sourceDevice.hostname || conn.source;
                        deviceNeighbors.push({
                            name: sourceName,
                            local_port: conn.target_port,
                            remote_port: conn.source_port
                        });
                    }
                }
            });
            
            if (deviceNeighbors.length > 0) {
                neighborList = '<h4>Connected Devices:</h4><ul>';
                deviceNeighbors.forEach(neighbor => {
                    neighborList += `<li>${neighbor.name} (${neighbor.local_port} → ${neighbor.remote_port})</li>`;
                });
                neighborList += '</ul>';
            }
            
            tooltip.html(`
                <div style="font-weight:bold; font-size:14px;">${d.hostname}</div>
                <div><strong>IP:</strong> ${d.ip}</div>
                <div><strong>Platform:</strong> ${d.platform}</div>
                <div><strong>Type:</strong> ${d.device_type}</div>
                <div><strong>Status:</strong> ${d.status}</div>
                ${neighborList}
                ${interfaceList}
            `)
            .style("left", (event.pageX + 10) + "px")
            .style("top", (event.pageY - 28) + "px");
        })
        .on("mouseout", function() {
            tooltip.transition()
                .duration(500)
                .style("opacity", 0);
        });
        
        // Update positions on simulation tick
        simulation.on("tick", () => {
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            linkText
                .attr("x", d => (d.source.x + d.target.x) / 2)
                .attr("y", d => (d.source.y + d.target.y) / 2);
            
            node
                .attr("transform", d => `translate(${d.x},${d.y})`);
        });
        
        // Drag functions
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
    </script>
</body>
</html>
"""
            
            # Write HTML file
            with open(output_file, 'w') as f:
                f.write(html_content)
                
            return True
            
        except Exception as e:
            logger.error(f"Error exporting topology to HTML: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

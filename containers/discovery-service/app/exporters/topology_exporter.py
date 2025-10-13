"""
Topology exporter for network discovery.

This module provides functions to export network topology in various formats.
"""

import json
import logging
from typing import Dict, List, Any, Optional
import os

logger = logging.getLogger(__name__)


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
            
            # Write JSON file
            with open(output_file, 'w') as f:
                json.dump(topology_data, f, indent=2)
                
            return True
            
        except Exception as e:
            logger.error(f"Error exporting topology to JSON: {str(e)}")
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
            
            # Generate HTML content with D3.js
            html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Network Topology</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
        #topology { width: 100%; height: 800px; }
        .node { cursor: pointer; }
        .link { stroke: #999; stroke-opacity: 0.6; }
        .node text { font-size: 12px; }
        .tooltip { position: absolute; background: white; border: 1px solid #ddd; 
                  border-radius: 4px; padding: 10px; pointer-events: none; }
    </style>
</head>
<body>
    <div id="topology"></div>
    <script>
        // Topology data
        const data = """ + json.dumps(topology_data) + """;
        
        // Create nodes and links for D3
        const nodes = [];
        const links = [];
        
        // Add nodes
        for (const [ip, device] of Object.entries(data.devices)) {
            const hostname = device.hostname || ip;
            const status = device.discovery_status || 'unknown';
            
            nodes.push({
                id: ip,
                hostname: hostname,
                ip: ip,
                platform: device.platform || 'unknown',
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
        const width = window.innerWidth;
        const height = 800;
        
        const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(200))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(width / 2, height / 2));
        
        const svg = d3.select("#topology")
            .append("svg")
            .attr("width", width)
            .attr("height", height);
        
        // Add zoom functionality
        const g = svg.append("g");
        svg.call(d3.zoom()
            .extent([[0, 0], [width, height]])
            .scaleExtent([0.1, 8])
            .on("zoom", (event) => {
                g.attr("transform", event.transform);
            }));
        
        // Create links
        const link = g.append("g")
            .selectAll("line")
            .data(links)
            .enter()
            .append("line")
            .attr("class", "link")
            .attr("stroke-width", 2);
        
        // Create link labels
        const linkText = g.append("g")
            .selectAll("text")
            .data(links)
            .enter()
            .append("text")
            .attr("font-size", "10px")
            .attr("text-anchor", "middle")
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
        
        // Node circles
        node.append("circle")
            .attr("r", 20)
            .attr("fill", d => {
                if (d.status === 'discovered') return "#69b3a2";
                if (d.status === 'failed') return "#ff7f7f";
                if (d.status === 'unreachable') return "#cccccc";
                return "#b8b8b8";
            });
        
        // Node labels
        node.append("text")
            .attr("dy", 30)
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
            
            tooltip.html(`<strong>${d.hostname}</strong><br>IP: ${d.ip}<br>Platform: ${d.platform}<br>Status: ${d.status}${interfaceList}`)
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
            return False

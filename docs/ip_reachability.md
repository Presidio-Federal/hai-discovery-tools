# IP Reachability Module

The IP Reachability module is a high-performance network discovery tool designed to efficiently scan large network segments and identify reachable hosts and open ports. This document provides detailed information about the module's functionality, configuration options, and usage examples.

## Overview

The IP Reachability module offers:

- Fast, asynchronous ICMP scanning using `fping`
- Concurrent TCP port probing
- Multiple fallback mechanisms for maximum compatibility
- Structured output with detailed scan results
- Integration with the discovery pipeline

## Operational Modes

The IP Reachability module can be used in three different operational modes:

1. **Subnet Mode**: Directly scans specified subnets for reachable hosts and open ports
2. **Seed-Device Mode**: Extracts subnets from seed devices and then scans those subnets
3. **Full-Pipeline Mode**: Runs IP reachability scan and then proceeds with neighbor discovery

## Configuration Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| subnets | List[str] | List of subnets in CIDR notation to scan |
| probe_ports | List[int] | List of TCP ports to probe (default: [22, 443]) |
| concurrency | int | Maximum number of concurrent operations (default: 200) |

## Output Format

The IP Reachability module produces a structured JSON output with the following format:

```json
{
  "results": [
    {
      "ip": "192.168.1.1",
      "icmp_reachable": true,
      "open_ports": [22, 443]
    },
    {
      "ip": "192.168.1.2",
      "icmp_reachable": true,
      "open_ports": [22, 80]
    },
    {
      "ip": "192.168.1.3",
      "icmp_reachable": false,
      "open_ports": []
    }
  ],
  "summary": {
    "total_scanned": 256,
    "icmp_reachable": 45,
    "port_22_open": 20,
    "port_443_open": 15,
    "port_80_open": 10
  },
  "duration_sec": 65.2,
  "timestamp": "2025-10-14T15:31:05Z"
}
```

## Implementation Details

### ICMP Scanning

The module uses a multi-level approach for ICMP scanning:

1. **Primary Method**: `fping` - A high-performance, parallel ping utility
   - Significantly faster than traditional ping for scanning large networks
   - Efficiently processes hundreds of hosts simultaneously
   - Minimal system resource usage

2. **First Fallback**: `aioping` - An asynchronous Python ICMP implementation
   - Pure Python solution that doesn't require external tools
   - Good performance through asynchronous operation
   - Works when system tools are not available

3. **Second Fallback**: Standard `ping` command
   - Universal availability on all systems
   - Slower but highly compatible
   - Used as last resort if other methods fail

### TCP Port Scanning

The module performs asynchronous TCP port scanning with the following features:

- Concurrent connection attempts with configurable concurrency
- Short timeouts (2 seconds) to quickly identify open ports
- Special handling for SSH ports using `asyncssh` for more reliable detection
- Graceful error handling and fallback mechanisms

### Seed Device Introspection

When operating in seed-device mode, the module:

1. Logs into seed devices using provided credentials
2. Runs commands to extract interface and routing information:
   - `show ip interface brief`
   - `show ip route connected`
3. Parses the output to identify connected subnets
4. Deduplicates and normalizes subnet information
5. Performs IP reachability scanning on the extracted subnets

## Usage Examples

### API Usage

Start an IP reachability scan in subnet mode:

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "subnet",
    "seed_devices": ["192.168.1.0/24", "10.0.0.0/24"],
    "probe_ports": [22, 80, 443],
    "concurrency": 200,
    "job_id": "reachability-scan-1"
  }'
```

Start a seed device introspection:

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "seed-device",
    "seed_devices": ["192.168.1.1:22", "10.0.0.1"],
    "credentials": [
      {"username": "admin", "password": "password1"},
      {"username": "cisco", "password": "password2"}
    ],
    "probe_ports": [22, 443]
  }'
```

Retrieve reachability results:

```bash
curl http://localhost:8080/discover/reachability-scan-1/reachability > reachability_matrix.json
```

## Performance Considerations

- For large networks (>1000 hosts), consider:
  - Increasing concurrency (up to 500 for powerful systems)
  - Limiting probe ports to the most essential (e.g., just 22 and 443)
  - Breaking scans into multiple smaller subnet ranges
  
- For optimal performance:
  - Ensure `fping` is installed in the container
  - Use appropriate timeouts based on network latency
  - Consider network bandwidth limitations

## Integration with Other Discovery Methods

The IP Reachability module is designed to work seamlessly with other discovery methods:

1. **As a Precursor**: Identify reachable hosts before deeper discovery
2. **As a Standalone Tool**: Quick network mapping without device login
3. **As Part of Full Pipeline**: Comprehensive discovery starting with reachability

When used in the full pipeline mode, the reachability results are used to:
- Prioritize connection attempts to hosts with open management ports
- Skip unreachable hosts to improve discovery efficiency
- Provide a complete picture of the network landscape

## Troubleshooting

Common issues and solutions:

- **Slow Performance**: 
  - Check if `fping` is installed and working
  - Reduce concurrency if network is congested
  - Split large subnets into smaller chunks

- **Missing Results**:
  - Verify subnet notation is correct (CIDR format)
  - Check for network firewalls blocking ICMP or TCP probes
  - Increase timeouts for high-latency networks

- **High Resource Usage**:
  - Lower concurrency value
  - Reduce number of probe ports
  - Process subnets in smaller batches

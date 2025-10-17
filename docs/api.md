# HAI Discovery Service API Documentation

This document provides detailed information about the HAI Discovery Service API endpoints, request/response formats, and usage examples.

## Base URL

When running locally:
```
http://localhost:8080
```

When using the container in production:
```
http://<container-host>:8080
```

## Authentication

The API currently does not require authentication for access. Network device credentials are provided in the discovery request payload.

## API Endpoints

### Start Discovery Job

Initiates a new network discovery job.

**Endpoint:** `POST /discover`

**Request Body:**

```json
{
  "seed_devices": ["192.168.1.1:22", "10.0.0.1", "172.16.1.1:4446", "192.168.2.0/24"],
  "credentials": [
    {"username": "admin", "password": "password1", "port": 22},
    {"username": "cisco", "password": "password2"}
  ],
  "mode": "full-pipeline",
  "method": "auto",
  "max_depth": 3,
  "timeout": 60,
  "concurrent_connections": 10,
  "probe_ports": [22, 443, 80],
  "concurrency": 200,
  "job_id": "custom-job-id-1"
}
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| seed_devices | array | List of seed devices (IP addresses or hostnames) to start discovery from. Can include port specification (IP:PORT) and subnet notation (CIDR). |
| credentials | array | List of credential sets to try when connecting to devices. |
| mode | string | Discovery mode to use. Options: "subnet", "seed-device", or "full-pipeline". Default: "full-pipeline" |
| method | string | Discovery method to use. Options: "auto", "neighbor_discovery", "subnet_scan", "ip_reachability", or "seed_device_introspection". When set to "auto", the method is selected based on the mode. Default: "auto" |
| max_depth | integer | Maximum depth of discovery (for neighbor_discovery). Default: 3 |
| timeout | integer | Connection timeout in seconds. Default: 60 |
| concurrent_connections | integer | Maximum number of concurrent device connections. Default: 10 |
| probe_ports | array | List of TCP ports to probe during IP reachability scanning. Default: [22, 443] |
| concurrency | integer | Maximum number of concurrent operations for IP reachability scanning. Default: 200 |
| job_id | string | Optional custom job ID. If not provided, a unique ID will be generated. |

**Response:**

```json
{
  "job_id": "d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f",
  "status": "pending",
  "mode": "full-pipeline",
  "endpoints": {
    "status": "/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f",
    "devices": "/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/devices",
    "topology": "/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/topology",
    "export": "/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/export",
    "reachability": "/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/reachability"
  },
  "message": "Discovery job started in full-pipeline mode. Use the endpoints above to check status and results."
}
```

### Get Discovery Job Status

Retrieves the status of a discovery job.

**Endpoint:** `GET /discover/{job_id}`

**Response:**

```json
{
  "job_id": "d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f",
  "status": "completed",
  "mode": "full-pipeline",
  "method": "neighbor_discovery",
  "start_time": "2025-10-14T15:30:00Z",
  "end_time": "2025-10-14T15:35:22Z",
  "summary": {
    "total_devices": 15,
    "successful_connections": 14,
    "failed_connections": 1,
    "device_types": {
      "cisco_ios": 10,
      "cisco_nxos": 3,
      "arista_eos": 2
    }
  },
  "preview": [
    {
      "hostname": "CORE-SW01",
      "ip": "192.168.1.1",
      "device_type": "cisco_ios",
      "status": "discovered"
    },
    {
      "hostname": "DIST-SW01",
      "ip": "192.168.1.2",
      "device_type": "cisco_ios",
      "status": "discovered"
    }
    // First 5 devices shown in preview
  ]
}
```

For subnet or seed-device modes, the response will include reachability information:

```json
{
  "job_id": "reachability-scan-1",
  "status": "completed",
  "mode": "subnet",
  "method": "ip_reachability",
  "start_time": "2025-10-14T15:30:00Z",
  "end_time": "2025-10-14T15:31:05Z",
  "artifact": "/app/data/exports/reachability-scan-1/reachability_matrix.json",
  "summary": {
    "total_scanned": 256,
    "icmp_reachable": 45,
    "port_22_open": 20,
    "port_443_open": 15
  }
}
```

### Get Discovered Devices

Retrieves the list of devices discovered in a job.

**Endpoint:** `GET /discover/{job_id}/devices`

**Response:**

```json
{
  "devices": [
    {
      "hostname": "CORE-SW01",
      "ip": "192.168.1.1",
      "device_type": "cisco_ios",
      "model": "WS-C3850-48T",
      "serial": "FOC1234A5BC",
      "os_version": "16.9.4",
      "uptime": "100 days, 5 hours, 30 minutes",
      "credentials_used": {
        "username": "admin",
        "port": "22"
      },
      "interfaces": [
        {
          "name": "GigabitEthernet1/0/1",
          "description": "Link to DIST-SW01",
          "status": "up",
          "mac_address": "00:11:22:33:44:55",
          "ip_address": "192.168.1.1",
          "connected_to": {
            "device": "DIST-SW01",
            "interface": "GigabitEthernet1/0/1"
          }
        },
        // More interfaces...
      ],
      "config": {
        "raw": "hostname CORE-SW01\n...",
        "parsed": {
          "hostname": "CORE-SW01",
          "interfaces": {
            "GigabitEthernet1/0/1": {
              "description": "Link to DIST-SW01",
              "ip_address": "192.168.1.1 255.255.255.0",
              "status": "no shutdown"
            }
            // More parsed config...
          }
        }
      }
    },
    // More devices...
  ]
}
```

### Get Network Topology

Returns an interactive HTML visualization of the network topology.

**Endpoint:** `GET /discover/{job_id}/topology`

**Response:**
HTML document containing an interactive network topology visualization.

### Export Discovery Data

Exports discovery data in various formats.

**Endpoint:** `GET /discover/{job_id}/export`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| format | string | Export format. Options: "json", "csv", "dot". Default: "json" |

**Response:**
Data in the requested format.

### Export Device Inventory

Exports device inventory as CSV.

**Endpoint:** `GET /discover/{job_id}/export/device_inventory`

**Response:**
CSV file containing device inventory information.

### Export Interface Inventory

Exports interface inventory as CSV.

**Endpoint:** `GET /discover/{job_id}/export/interface_inventory`

**Response:**
CSV file containing interface inventory information.

### Get Reachability Results

Retrieves the IP reachability scan results for a discovery job.

**Endpoint:** `GET /discover/{job_id}/reachability`

**Response:**

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
    // More results...
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

## Error Responses

The API returns standard HTTP status codes:

- `200 OK` - Request succeeded
- `400 Bad Request` - Invalid request parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

Error response format:

```json
{
  "error": "Error message",
  "detail": "Detailed error information"
}
```

## Usage Examples

### Starting an IP Reachability Scan (Subnet Mode)

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

### Starting a Seed Device Introspection (Seed-Device Mode)

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

### Starting a Full Discovery Pipeline

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "full-pipeline",
    "seed_devices": ["192.168.1.1:22", "10.0.0.1"],
    "credentials": [
      {"username": "admin", "password": "password1"},
      {"username": "cisco", "password": "password2"}
    ],
    "method": "neighbor_discovery",
    "max_depth": 3
  }'
```

### Checking Job Status

```bash
curl http://localhost:8080/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f
```

### Exporting Discovery Data as JSON

```bash
curl http://localhost:8080/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/export?format=json > discovery_data.json
```

### Getting Topology Visualization

```bash
curl http://localhost:8080/discover/d8f91c3e-6c7b-4a2d-8f1e-5a9b7e3c8d2f/topology > topology.html
```

### Getting Reachability Results

```bash
curl http://localhost:8080/discover/reachability-scan-1/reachability > reachability_matrix.json
```

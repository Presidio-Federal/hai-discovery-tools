# HAI Network Discovery Tools

A collection of tools for network device discovery and configuration extraction.

## Discovery Service

The Discovery Service is a containerized application that discovers network devices, extracts their configurations, and maps network topology.

### Features

- **Network Discovery**:
  - IP reachability scanning with ICMP and TCP port probes
  - Subnet-based discovery for large network segments
  - Seed device introspection to extract connected networks
  - CDP/LLDP neighbor-based discovery for detailed topology mapping
- **Device Management**:
  - Extracts device configurations and parses them into structured data
  - Supports multi-vendor environments through Netmiko
  - Identifies device types, models, and operating systems
- **Visualization & Export**:
  - Maps network topology with port-to-port connections
  - Provides interactive visualization of the network topology
  - Exports data in various formats (JSON, HTML)
  - Generates reachability matrices for network analysis

### Getting Started

#### Building the Container

```bash
docker build -t hai-discovery-tools:latest -f containers/discovery-service/Dockerfile .
```

#### Running the Container

```bash
docker run -p 8080:8080 hai-discovery-tools:latest
```

#### Using the API

The discovery service supports three operational modes:

1. **Subnet Mode**: Performs IP reachability scanning on specified subnets
2. **Seed-Device Mode**: Extracts subnets from seed devices and runs IP reachability scanning
3. **Full-Pipeline Mode**: Runs complete discovery including reachability, neighbor discovery, and topology mapping

Start a discovery job in subnet mode:

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "subnet",
    "seed_devices": ["192.168.1.0/24"],
    "credentials": [
      {"username": "admin", "password": "password1"}
    ],
    "probe_ports": [22, 443, 80],
    "concurrency": 200
  }'
```

Start a discovery job in seed-device mode:

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "seed-device",
    "seed_devices": [
      "192.168.1.1:22", 
      "10.0.0.1:22"
    ],
    "credentials": [
      {"username": "admin", "password": "password1"},
      {"username": "cisco", "password": "password2"}
    ],
    "probe_ports": [22, 443]
  }'
```

Start a full discovery job:

```bash
curl -X POST "http://localhost:8080/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "full-pipeline",
    "seed_devices": [
      "192.168.1.1:22", 
      "10.0.0.1:22", 
      "172.16.1.1:4446"
    ],
    "credentials": [
      {"username": "admin", "password": "password1"},
      {"username": "cisco", "password": "password2"}
    ],
    "method": "neighbor_discovery",
    "max_depth": 3
  }'
```

Get discovery status:

```bash
curl http://localhost:8080/discover/{job_id}
```

Get discovered devices:

```bash
curl http://localhost:8080/discover/{job_id}/devices
```

View network topology:

```bash
curl http://localhost:8080/discover/{job_id}/topology > topology.html
```

Export discovery data:

```bash
curl http://localhost:8080/discover/{job_id}/export?format=json > discovery_data.json
```

### GitHub Actions Integration

This repository includes GitHub Actions workflows for:

1. Building and pushing the container to GitHub Container Registry
2. Running network discovery using the container

#### Setting Up GitHub Actions

1. Create a GitHub repository secret named `DEVICE_PASSWORD` with your network device password.
2. Push your code to GitHub.
3. The container will be automatically built and pushed to GHCR when changes are made to the discovery service.
4. You can manually trigger a discovery job from the Actions tab.

#### Using the Container in Other Projects

```yaml
jobs:
  network-discovery:
    runs-on: ubuntu-latest
    steps:
      - name: Run network discovery
        uses: docker://ghcr.io/yourusername/hai-discovery-tools/discovery-service:latest
        with:
          seed_devices: "192.168.1.1:22"
          username: "admin"
          password: ${{ secrets.DEVICE_PASSWORD }}
```

### API Documentation

The Discovery Service provides a RESTful API for network discovery operations.

#### Endpoints

- `POST /discover` - Start a discovery job
- `GET /discover/{job_id}` - Get job status
- `GET /discover/{job_id}/devices` - Get discovered devices
- `GET /discover/{job_id}/topology` - Get network topology visualization
- `GET /discover/{job_id}/export` - Export discovery data
- `GET /discover/{job_id}/reachability` - Get IP reachability results
- `GET /discover/{job_id}/export/device_inventory` - Export device inventory as JSON
- `GET /discover/{job_id}/export/interface_inventory` - Export interface inventory as JSON

For detailed documentation, see:
- [API Documentation](docs/api.md)
- [IP Reachability Module](docs/ip_reachability.md)
- [GitHub Actions Guide](docs/github-actions.md)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
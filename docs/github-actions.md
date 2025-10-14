# GitHub Actions Integration

This document explains how to use the GitHub Actions workflows for building and running the network discovery container.

## Setting Up Secrets

Before you can use the workflows, you need to set up the following secrets in your GitHub repository:

1. Go to your GitHub repository → Settings → Secrets and variables → Actions
2. Add the following secrets:

| Secret Name | Description |
|-------------|-------------|
| `DEVICE_PASSWORD` | Default password for device authentication (fallback) |
| `DEVICE_PASSWORD_1` | Password for the first username in the credentials list |
| `DEVICE_PASSWORD_2` | Password for the second username in the credentials list |
| `DEVICE_PASSWORD_3` | Password for the third username in the credentials list |
| ... | Add more as needed |

## Build and Push Container Workflow

This workflow builds the discovery service container and pushes it to GitHub Container Registry (GHCR).

### Triggers

- Push to `main` branch (when changes are made to the discovery service)
- Pull request to `main` branch (build only, no push)
- Manual trigger from Actions tab

### Usage

1. Go to the Actions tab in your GitHub repository
2. Select the "Build and Push Container" workflow
3. Click "Run workflow"
4. The workflow will build the container and push it to GHCR

### Container Access

The container will be available at:
```
ghcr.io/[your-username]/hai-discovery-tools/discovery-service:latest
```

You can pull it with:
```bash
docker pull ghcr.io/[your-username]/hai-discovery-tools/discovery-service:latest
```

## Network Discovery Workflow

This workflow runs a network discovery job using the container.

### Inputs

| Input | Description |
|-------|-------------|
| `seed_devices` | Comma-separated list of devices to start discovery from (e.g., `192.168.1.1,10.0.0.1:22`) |
| `credentials` | Comma-separated list of usernames for device authentication (e.g., `admin,cisco,operator`) |
| `discovery_method` | Method to use for discovery (`neighbor_discovery` or `subnet_scan`) |
| `max_depth` | Maximum discovery depth (default: 3) |
| `timeout` | Connection timeout in seconds (default: 60) |

### Credentials Setup

The workflow uses a dynamic credential system:

1. You provide a comma-separated list of usernames in the `credentials` input
2. The workflow looks for corresponding password secrets:
   - `DEVICE_PASSWORD_1` for the first username
   - `DEVICE_PASSWORD_2` for the second username
   - And so on...
3. If a specific password secret is not found, it falls back to `DEVICE_PASSWORD`

### Usage

1. Go to the Actions tab in your GitHub repository
2. Select the "Network Discovery" workflow
3. Click "Run workflow"
4. Fill in the parameters:
   - Seed devices: `192.168.1.1,10.0.0.1:22,172.16.1.1:4446`
   - Credentials: `admin,cisco,operator`
   - Discovery method: `neighbor_discovery`
   - Max depth: `3`
   - Timeout: `60`
5. Click "Run workflow"

![GitHub Actions Workflow Input Form](https://i.imgur.com/example.png)

This is where you enter the comma-separated list of usernames in the "Credentials" field.

### Results

After the workflow completes, you can download the discovery results as artifacts:

1. Go to the completed workflow run
2. Scroll down to the "Artifacts" section
3. Download the "discovery-results" artifact
4. Extract the ZIP file to access:
   - `discovery_data.json` - Complete discovery data in JSON format
   - `device_inventory.csv` - Device inventory in CSV format
   - `interface_inventory.csv` - Interface inventory in CSV format
   - `topology.html` - Interactive visualization of the network topology

## Using in Other Workflows

You can use the discovery container in other workflows:

```yaml
jobs:
  network-discovery:
    runs-on: ubuntu-latest
    steps:
      - name: Run network discovery
        run: |
          docker run -d --name discovery -p 8080:8080 ghcr.io/[your-username]/hai-discovery-tools/discovery-service:latest
          
          # Wait for service to start
          sleep 5
          
          # Run discovery
          curl -X POST "http://localhost:8080/discover" \
            -H "Content-Type: application/json" \
            -d '{
              "seed_devices": ["192.168.1.1", "10.0.0.1"],
              "credentials": [
                {"username": "admin", "password": "${{ secrets.DEVICE_PASSWORD }}"},
                {"username": "cisco", "password": "${{ secrets.CISCO_PASSWORD }}"}
              ],
              "method": "neighbor_discovery"
            }'
```

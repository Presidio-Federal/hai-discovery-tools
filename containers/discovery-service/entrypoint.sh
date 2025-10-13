#!/bin/bash
set -e

echo "Starting HAI Discovery Service (mode: ${MODE})"

# Default to API mode if MODE is not provided
MODE=${MODE:-api}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8080}
LOG_LEVEL=${LOG_LEVEL:-info}

if [ "$MODE" = "mcp" ]; then
    echo "Launching FastMCP mode..."
    exec fastmcp run app.mcp_tool --transport http --host "$HOST" --port "$PORT"
else
    echo "Launching API mode..."
    exec uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level "$LOG_LEVEL"
fi
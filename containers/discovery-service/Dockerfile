# ---- build ----
FROM python:3.11-slim AS build
WORKDIR /app
    
# Install system dependencies for Python builds and network tools
RUN apt-get update && apt-get install -y \
    gcc \
    nmap \
    fping \
    netcat-openbsd \
    iputils-ping \
    traceroute \
    snmp \
    snmpd \
    sshpass \
    openssh-client \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*
    
# Copy requirements and install Python dependencies
COPY containers/discovery-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
    
# Copy Python application source and setup.py
COPY containers/discovery-service/app ./app
COPY containers/discovery-service/setup.py .
RUN pip install -e .
    
# ---- runtime ----
FROM python:3.11-slim
WORKDIR /app
    
# Install lightweight runtime dependencies
RUN apt-get update && apt-get install -y \
    openssh-client \
    iputils-ping \
    traceroute \
    nmap \
    fping \
    netcat-openbsd \
    snmp \
    snmpd \
    && rm -rf /var/lib/apt/lists/*
    
# Copy installed packages and application
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /app/app ./app
COPY --from=build /app/setup.py .
RUN pip install -e .
    
# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/data/exports && \
    chown -R app:app /app
USER app
    
# Expose FastMCP / API port
EXPOSE 8080
    
# Add Python path for module import
ENV PYTHONPATH=/app
    
# Start service in API mode by default
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
    
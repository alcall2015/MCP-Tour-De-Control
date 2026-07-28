FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    sip-tester \
    python3 \
    python3-pip \
    python3-venv \
    sox \
    ffmpeg \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY scenarios/ /app/scenarios/
COPY media/ /app/media/
RUN chmod +x /app/media/generate_pcap.sh && /app/media/generate_pcap.sh

COPY *.py /app/

ENV MCP_PORT=9090

CMD ["python3", "/app/mcp_server.py"]

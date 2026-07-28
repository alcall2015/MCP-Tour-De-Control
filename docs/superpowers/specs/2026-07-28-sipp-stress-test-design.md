# SIPp Stress Test Module — Design Spec

**Date:** 2026-07-28
**Status:** Approved

## Overview

A new SIPp-based stress testing module for MCP Tour De Control. A dedicated Docker container (`sipp-stress`) runs SIPp and exposes a FastMCP server over HTTP. The backend connects to it as an MCP server to launch, monitor, and collect metrics from SIP stress tests targeting Kamailio + RTPEngine. A new "Stress Call" tab in the frontend provides test configuration, live monitoring, and comparison.

## Architecture

```
React UI (Stress Call tab)
    ↕ REST API
FastAPI Backend
    ↕ MCP Client (HTTP)
sipp-stress Container (FastMCP server :9090)
    ↕ subprocess
SIPp UAC (sender) + SIPp UAS (receiver + RTP analysis)
    ↕ SIP/RTP
Kamailio + RTPEngine (target)
```

### Core Flow

1. User configures a stress test in the UI (target, scenario, CPS, duration, ramp-up, media type)
2. Backend creates a `stress_test` record, calls MCP `start_test()` on the sipp-stress container
3. MCP server launches SIPp UAC (port 5070) + SIPp UAS (port 5080) as subprocesses
4. SIPp UAC sends INVITEs to Kamailio, which routes them to SIPp UAS via RTPEngine
5. SIPp UAS responds with media (silence/tone/voice), analyzes received RTP
6. Backend polls `get_status`/`get_metrics`/`get_rtp_stats` every 5 seconds, stores snapshots in DB
7. Frontend polls latest metrics for live display
8. Test completes → final snapshot stored, UI shows full results

### Network

`network_mode: host` on the sipp-stress container — SIPp needs a real IP for SIP/RTP. Docker NAT breaks SDP IP addresses.

## Container: sipp-stress

### Dockerfile

Base: `debian:bookworm-slim` with SIPp (`sip-tester`), Python 3, sox, ffmpeg. FastMCP server listens on HTTP port 9090.

### Structure

```
sipp-stress/
├── Dockerfile
├── mcp_server.py              # FastMCP server with 7 tools
├── sipp_runner.py             # Launch/manage SIPp subprocesses
├── metrics_parser.py          # Parse SIPp CSV stats → dict
├── rtp_analyzer.py            # Compute jitter, loss, MOS from RTP stats
├── scenarios/
│   ├── basic_call_uac.xml     # INVITE → 200 → pause → BYE
│   ├── short_call_uac.xml     # INVITE → 200 → BYE (1s)
│   ├── cancel_call_uac.xml    # INVITE → CANCEL
│   ├── reinvite_call_uac.xml  # INVITE → 200 → re-INVITE → BYE
│   └── receiver_uas.xml       # Receive INVITE → 200 + media
├── media/
│   ├── generate_pcap.sh       # Build script: WAV → pcap
│   ├── silence.wav
│   ├── tone.wav
│   └── voice.wav
└── tests/
    └── test_metrics_parser.py
```

### MCP Tools

```
start_test(
    target_host: str,
    target_port: int = 5060,
    scenario: str = "basic_call",
    cps: int = 10,
    max_calls: int = 100,
    duration: int = 60,
    call_duration: int = 10,
    ramp_up: int = 0,
    ramp_step: int = 1,
    transport: str = "udp",
    caller_id: str = "sipp",
    media_type: str = "random"
) → { test_id, status, pid }

stop_test(test_id: str) → { status }

get_status(test_id: str) → {
    status: running|completed|failed|stopped,
    elapsed_seconds, current_cps,
    active_calls, total_calls_attempted
}

get_metrics(test_id: str) → {
    total_calls, successful_calls, failed_calls,
    asr_percent, pdd_avg_ms, pdd_p95_ms,
    setup_time_avg_ms, cps_achieved,
    retransmissions, failed_by_code: {408: n, ...},
    duration_seconds, max_concurrent_calls,
    ramp_up_curve: [{second, cps}...]
}

get_rtp_stats(test_id: str) → {
    packets_sent, packets_received,
    packet_loss_percent, jitter_avg_ms, jitter_max_ms,
    rtt_avg_ms, rtt_max_ms,
    mos_score, out_of_order_packets,
    throughput_kbps
}

list_scenarios() → [{ name, description, type: "uac"|"uas" }]

list_tests() → [{ test_id, scenario, status, started_at }]
```

### SIPp Scenarios

**UAC scenarios (4):**
- `basic_call` — INVITE → 180 → 200 → ACK → RTP pause → BYE. Standard call testing routing + media relay.
- `short_call` — Same flow, 1s duration. Tests max CPS and rapid setup/teardown.
- `cancel_call` — INVITE → 100 → CANCEL → 487 → ACK. Tests CANCEL handling.
- `reinvite_call` — Full call + re-INVITE mid-call. Tests re-INVITE and RTPEngine SDP renegotiation.

**UAS scenario (1):**
- `receiver` — Listens for INVITE, responds 180 → 200 OK with SDP, plays media pcap, waits for BYE. Media selection: random per call (via SIPp injection CSV), or fixed (silence/tone/voice).

### Media Files

Generated at Docker build time via `sox` + custom pcap encoding script:
- `silence.pcap` — G.711 alaw, 20ms ptime, silence bytes
- `tone.pcap` — G.711 alaw, 440Hz sine wave
- `voice.pcap` — G.711 alaw, voice sample (~10s loop)

For `media_type=random`, the MCP server generates an injection CSV that assigns random media per call.

### MOS Calculation

Simplified E-model (ITU-T G.107):
```
R = 93.2 - Id - Ie
Id = 0.024 * delay + 0.11 * (delay - 177.3) * H(delay - 177.3)
Ie = packet_loss_percent * 2.5
MOS = 1 + 0.035 * R + R * (R - 60) * (100 - R) * 7e-6
```
Where delay = RTT/2 + jitter, H = Heaviside step function.

## Data Model

### stress_test

| Column         | Type      | Notes                              |
|----------------|-----------|-------------------------------------|
| id             | UUID PK   |                                     |
| name           | VARCHAR   |                                     |
| scenario       | VARCHAR   | basic_call, short_call, etc.       |
| target_host    | VARCHAR   |                                     |
| target_port    | INTEGER   | default 5060                       |
| transport      | VARCHAR   | udp or tcp                         |
| cps            | INTEGER   | calls per second target            |
| max_calls      | INTEGER   |                                     |
| duration       | INTEGER   | max test duration in seconds       |
| call_duration  | INTEGER   | per-call duration in seconds       |
| ramp_up        | INTEGER   | seconds to reach target CPS        |
| ramp_step      | INTEGER   | CPS increment per second           |
| caller_id      | VARCHAR   |                                     |
| media_type     | VARCHAR   | random, silence, tone, voice       |
| status         | VARCHAR   | pending, running, completed, failed, stopped |
| remote_test_id | VARCHAR   | UUID from MCP server               |
| started_at     | TIMESTAMP |                                     |
| finished_at    | TIMESTAMP |                                     |
| created_at     | TIMESTAMP |                                     |

### stress_test_metrics

| Column            | Type      | Notes                          |
|-------------------|-----------|--------------------------------|
| id                | UUID PK   |                                |
| stress_test_id    | UUID FK   | → stress_test                  |
| total_calls       | INTEGER   |                                |
| successful_calls  | INTEGER   |                                |
| failed_calls      | INTEGER   |                                |
| asr_percent       | FLOAT     |                                |
| pdd_avg_ms        | FLOAT     |                                |
| pdd_p95_ms        | FLOAT     |                                |
| setup_time_avg_ms | FLOAT     |                                |
| cps_achieved      | FLOAT     |                                |
| retransmissions   | INTEGER   |                                |
| failed_by_code    | JSONB     | {408: n, 486: n, 503: n, ...} |
| packets_sent      | INTEGER   |                                |
| packets_received  | INTEGER   |                                |
| packet_loss_pct   | FLOAT     |                                |
| jitter_avg_ms     | FLOAT     |                                |
| jitter_max_ms     | FLOAT     |                                |
| rtt_avg_ms        | FLOAT     |                                |
| rtt_max_ms        | FLOAT     |                                |
| mos_score         | FLOAT     |                                |
| out_of_order      | INTEGER   |                                |
| throughput_kbps   | FLOAT     |                                |
| duration_seconds  | INTEGER   |                                |
| max_concurrent    | INTEGER   |                                |
| ramp_up_curve     | JSONB     | [{second, cps}, ...]           |
| collected_at      | TIMESTAMP |                                |

### Relations

- `stress_test` 1→N `stress_test_metrics` (snapshots every 5s + final)

## API

```
PREFIX: /api/v1

Stress Tests:
  GET    /stress-tests                    # list all (paginated)
  POST   /stress-tests                    # create + launch
  GET    /stress-tests/:id                # detail + latest metrics
  DELETE /stress-tests/:id                # delete test + metrics
  POST   /stress-tests/:id/stop           # stop running test
  GET    /stress-tests/:id/metrics        # full timeline
  GET    /stress-tests/:id/metrics/latest  # last snapshot
  POST   /stress-tests/compare            # body: {test_ids: []}

Scenarios:
  GET    /stress-tests/scenarios          # list from MCP
```

### POST /stress-tests flow

1. Create `stress_test` record (status=pending)
2. Call MCP `start_test()` on sipp-stress container
3. Update status=running, store remote_test_id
4. Launch `asyncio.create_task(_poll_metrics())` — polls every 5s until test ends
5. Return stress_test to client

### POST /stress-tests/:id/stop flow

1. Call MCP `stop_test(remote_test_id)`
2. Collect final metrics via `get_metrics` + `get_rtp_stats`
3. Update status=stopped, finished_at=now

## Backend Service

```python
class StressTestService:
    MCP_URL from env var SIPP_MCP_URL (default http://localhost:9090/mcp)

    async launch_test(config, session) → StressTest
    async stop_test(test_id, session) → StressTest
    async _poll_metrics(test_id, remote_test_id, session)  # background task
    async compare_tests(test_ids, session) → list[StressTestMetrics]
```

Auto-registration: on backend startup, if no MCP server named "sipp-stress" exists, create one with transport=http, url=$SIPP_MCP_URL.

## Frontend

New tab "Stress Call" added to TabNav and App.tsx routing.

### Components

```
src/pages/StressCallPage.tsx
src/components/StressCall/
├── StressTestList.tsx          # test cards with progress, ASR, MOS preview
├── StressTestForm.tsx          # config form (target, scenario, CPS, ramp-up, media)
├── StressTestDetail.tsx        # live monitoring view
├── StressTestCompare.tsx       # side-by-side comparison table
├── MetricsGauges.tsx           # 5 gauges: ASR, MOS, CPS, Loss, PDD
├── SipMetricsCard.tsx          # SIP metrics detail card
├── RtpMetricsCard.tsx          # RTP metrics detail card
└── CpsChart.tsx                # SVG polyline chart of CPS over time
```

### Live Monitoring

- `StressTestDetail` polls `GET /stress-tests/:id/metrics/latest` every 3s when status=running
- Gauges and metrics update in real time
- CPS chart accumulates points from ramp_up_curve
- Polling stops when status != running

### Compare View

- Select 2-3 completed tests
- Side-by-side table of final metrics
- Delta indicators (▲ better, ▼ degraded) per metric

### Design

Follows existing "Control Tower at Night" theme:
- Amber accent for active tests and gauges
- Green/red for pass/fail metrics
- Cards with hover glow
- Space Grotesk headings
- MOS gauge: green (4+), amber (3-4), red (<3)

## Docker Compose Changes

```yaml
sipp-stress:
  build: ./sipp-stress
  network_mode: host
  environment:
    MCP_PORT: 9090
  volumes:
    - sipp-results:/tmp/sipp
  depends_on:
    - backend

backend:
  environment:
    SIPP_MCP_URL: http://localhost:9090/mcp  # host network
```

## Modified Existing Files

| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Add StressTest, StressTestMetrics |
| `backend/app/schemas/__init__.py` | Add stress test schemas |
| `backend/app/main.py` | Register stress_tests router, auto-register sipp-stress MCP |
| `frontend/src/lib/api.ts` | Add stress test types + API functions |
| `frontend/src/App.tsx` | Add /stress-call route |
| `frontend/src/components/Layout/TabNav.tsx` | Add Stress Call tab |
| `docker-compose.yml` | Add sipp-stress service |

## Metrics Collected

### SIP (signaling)
- ASR (Answer Seizure Ratio) — % successful calls
- PDD (Post Dial Delay) — INVITE to 180/200, avg + p95
- Call Setup Time — INVITE to 200 OK
- CPS achieved vs requested
- Retransmissions count
- Failed calls by SIP response code (408, 486, 503, etc.)

### RTP (media)
- Packet loss %
- Jitter — avg and max (ms)
- RTT — avg and max (ms)
- MOS score (E-model, 1.0–4.4 scale)
- Out of order packets
- Throughput (kbps)

### System
- Total test duration
- Max concurrent calls reached
- Ramp-up curve (CPS per second timeline)

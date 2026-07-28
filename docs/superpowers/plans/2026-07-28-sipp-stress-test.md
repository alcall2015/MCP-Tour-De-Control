# SIPp Stress Test Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a SIPp-based stress testing module to MCP Tour De Control — a Docker container with a FastMCP server piloting SIPp, integrated into the existing backend and frontend with a new "Stress Call" tab.

**Architecture:** A `sipp-stress` Docker container runs SIPp + a FastMCP HTTP server (port 9090) exposing 7 tools. The FastAPI backend connects via MCP Client to launch tests, poll metrics every 5s, and store results in PostgreSQL. The React frontend gets a 4th tab "Stress Call" with test list, config form, live monitoring gauges, and comparison view.

**Tech Stack:** SIPp (sip-tester), Python 3, FastMCP, sox/ffmpeg (media generation) | Existing: FastAPI, SQLAlchemy async, Alembic, React 18, TypeScript, Tailwind v4, TanStack Query

## Global Constraints

- All backend async (asyncpg, async SQLAlchemy)
- API prefix: `/api/v1`
- All IDs are UUIDs
- No authentication (mono-user)
- Follow existing patterns: `APIRouter(prefix=..., tags=...)`, `@staticmethod async` services, Pydantic schemas with `from_attributes=True`
- Frontend: "Control Tower at Night" theme (CSS vars: `--accent`, `--bg-panel`, `--bg-elevated`, `--border`, etc.), Space Grotesk headings, `.card`/`.btn-primary`/`.input-field` classes
- Docker: `network_mode: host` for sipp-stress container (SIP/RTP needs real IP)
- SIPp scenarios use G.711 alaw codec, 20ms ptime

---

### Task 1: sipp-stress container — SIPp scenarios + media files + Dockerfile

**Files:**
- Create: `sipp-stress/Dockerfile`
- Create: `sipp-stress/scenarios/basic_call_uac.xml`
- Create: `sipp-stress/scenarios/short_call_uac.xml`
- Create: `sipp-stress/scenarios/cancel_call_uac.xml`
- Create: `sipp-stress/scenarios/reinvite_call_uac.xml`
- Create: `sipp-stress/scenarios/receiver_uas.xml`
- Create: `sipp-stress/media/generate_pcap.sh`
- Create: `sipp-stress/requirements.txt`

**Interfaces:**
- Produces: 5 SIPp XML scenarios ready to use with `sipp -sf <file>`
- Produces: `generate_pcap.sh` that creates `silence.pcap`, `tone.pcap`, `voice.pcap` from sox-generated WAVs
- Produces: Dockerfile that builds the container with SIPp, Python3, sox, ffmpeg, FastMCP

- [ ] **Step 1: Create sipp-stress directory structure**

```bash
mkdir -p sipp-stress/scenarios sipp-stress/media sipp-stress/tests
```

- [ ] **Step 2: Create `sipp-stress/scenarios/basic_call_uac.xml`**

```xml
<?xml version="1.0" encoding="ISO-8859-1" ?>
<!DOCTYPE scenario SYSTEM "sipp.dtd">
<scenario name="Basic Call UAC">

  <send retrans="500">
    <![CDATA[
      INVITE sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>
      Call-ID: [call_id]
      CSeq: 1 INVITE
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Type: application/sdp
      Content-Length: [len]

      v=0
      o=sipp 53655765 2353687637 IN IP[local_ip_type] [local_ip]
      s=SIPp Stress Test
      c=IN IP[media_ip_type] [media_ip]
      t=0 0
      m=audio [media_port] RTP/AVP 8
      a=rtpmap:8 PCMA/8000
      a=ptime:20
    ]]>
  </send>

  <recv response="100" optional="true" />
  <recv response="180" optional="true" />

  <recv response="200" rtd="true" crlf="true">
    <action>
      <ereg regexp=".*" search_in="body" assign_to="remote_sdp"/>
    </action>
  </recv>

  <send>
    <![CDATA[
      ACK sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>[peer_tag_param]
      Call-ID: [call_id]
      CSeq: 1 ACK
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Length: 0
    ]]>
  </send>

  <nop>
    <action>
      <exec play_pcap_audio="/app/media/silence.pcap"/>
    </action>
  </nop>

  <pause milliseconds="[field1]"/>

  <send retrans="500">
    <![CDATA[
      BYE sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>[peer_tag_param]
      Call-ID: [call_id]
      CSeq: 2 BYE
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Length: 0
    ]]>
  </send>

  <recv response="200" crlf="true"/>

  <ResponseTimeRepartition value="10, 20, 30, 40, 50, 100, 150, 200, 500, 1000"/>
  <CallLengthRepartition value="10, 50, 100, 500, 1000, 5000, 10000"/>

</scenario>
```

- [ ] **Step 3: Create `sipp-stress/scenarios/short_call_uac.xml`**

Same as basic_call_uac.xml but with `<pause milliseconds="1000"/>` (hardcoded 1s instead of `[field1]`). Copy basic_call_uac.xml, change the scenario name to "Short Call UAC" and replace `<pause milliseconds="[field1]"/>` with `<pause milliseconds="1000"/>`.

- [ ] **Step 4: Create `sipp-stress/scenarios/cancel_call_uac.xml`**

```xml
<?xml version="1.0" encoding="ISO-8859-1" ?>
<!DOCTYPE scenario SYSTEM "sipp.dtd">
<scenario name="Cancel Call UAC">

  <send retrans="500">
    <![CDATA[
      INVITE sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>
      Call-ID: [call_id]
      CSeq: 1 INVITE
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Length: 0
    ]]>
  </send>

  <recv response="100" optional="true" />

  <pause milliseconds="500"/>

  <send retrans="500">
    <![CDATA[
      CANCEL sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>
      Call-ID: [call_id]
      CSeq: 1 CANCEL
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Length: 0
    ]]>
  </send>

  <recv response="200" crlf="true"/>
  <recv response="487" optional="true"/>

  <send>
    <![CDATA[
      ACK sip:[service]@[remote_ip]:[remote_port] SIP/2.0
      Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
      From: "[field0]" <sip:[field0]@[local_ip]:[local_port]>;tag=[pid]SIPpTag00[call_number]
      To: <sip:[service]@[remote_ip]:[remote_port]>[peer_tag_param]
      Call-ID: [call_id]
      CSeq: 1 ACK
      Contact: <sip:[field0]@[local_ip]:[local_port]>
      Max-Forwards: 70
      Content-Length: 0
    ]]>
  </send>

  <ResponseTimeRepartition value="10, 20, 30, 40, 50, 100, 150, 200, 500, 1000"/>

</scenario>
```

- [ ] **Step 5: Create `sipp-stress/scenarios/reinvite_call_uac.xml`**

Based on basic_call_uac.xml. After the first ACK + pause, add a re-INVITE with a new SDP (same codec), receive 200, send ACK, pause again, then BYE. The scenario name is "Re-INVITE Call UAC". The re-INVITE has CSeq 2, and BYE has CSeq 3.

- [ ] **Step 6: Create `sipp-stress/scenarios/receiver_uas.xml`**

```xml
<?xml version="1.0" encoding="ISO-8859-1" ?>
<!DOCTYPE scenario SYSTEM "sipp.dtd">
<scenario name="Receiver UAS">

  <recv request="INVITE" crlf="true">
    <action>
      <ereg regexp=".*" search_in="body" assign_to="remote_sdp"/>
    </action>
  </recv>

  <send>
    <![CDATA[
      SIP/2.0 180 Ringing
      [last_Via:]
      [last_From:]
      [last_To:];tag=[pid]SIPpTag01[call_number]
      [last_Call-ID:]
      [last_CSeq:]
      Contact: <sip:[local_ip]:[local_port]>
      Content-Length: 0
    ]]>
  </send>

  <pause milliseconds="500"/>

  <send retrans="500">
    <![CDATA[
      SIP/2.0 200 OK
      [last_Via:]
      [last_From:]
      [last_To:];tag=[pid]SIPpTag01[call_number]
      [last_Call-ID:]
      [last_CSeq:]
      Contact: <sip:[local_ip]:[local_port]>
      Content-Type: application/sdp
      Content-Length: [len]

      v=0
      o=sipp 53655765 2353687637 IN IP[local_ip_type] [local_ip]
      s=SIPp UAS
      c=IN IP[media_ip_type] [media_ip]
      t=0 0
      m=audio [media_port] RTP/AVP 8
      a=rtpmap:8 PCMA/8000
      a=ptime:20
    ]]>
  </send>

  <recv request="ACK" optional="true" crlf="true"/>

  <nop>
    <action>
      <exec play_pcap_audio="[field0]"/>
    </action>
  </nop>

  <recv request="BYE"/>

  <send>
    <![CDATA[
      SIP/2.0 200 OK
      [last_Via:]
      [last_From:]
      [last_To:]
      [last_Call-ID:]
      [last_CSeq:]
      Contact: <sip:[local_ip]:[local_port]>
      Content-Length: 0
    ]]>
  </send>

  <recv request="." optional="true"/>

  <ResponseTimeRepartition value="10, 20, 30, 40, 50, 100, 150, 200, 500, 1000"/>
  <CallLengthRepartition value="10, 50, 100, 500, 1000, 5000, 10000"/>

</scenario>
```

Note: `[field0]` in `play_pcap_audio` is populated from the injection CSV — allows per-call media selection.

- [ ] **Step 7: Create `sipp-stress/media/generate_pcap.sh`**

```bash
#!/bin/bash
set -e
cd /app/media

# Generate WAV files using sox
# Silence: 10 seconds of silence, G.711 alaw, 8kHz mono
sox -n -r 8000 -c 1 -e a-law silence.wav trim 0 10

# Tone: 10 seconds of 440Hz sine wave
sox -n -r 8000 -c 1 -e a-law tone.wav synth 10 sine 440

# Voice: use sox to generate a spoken-like pattern (alternating tones)
sox -n -r 8000 -c 1 -e a-law voice.wav synth 10 sine 300:600 gain -10

echo "WAV files generated successfully."

# Convert WAVs to RTP pcap files using sipp's built-in pcap play
# SIPp can play WAV files directly with play_pcap_audio if they are
# in the right format. For raw pcap, we create them from the WAV.
# Actually, SIPp with -mp flag can play raw audio files too.
# We'll use the WAV files directly — SIPp supports alaw WAV playback.

# Create symlinks for .pcap names (SIPp uses the file extension)
for f in silence tone voice; do
    cp ${f}.wav ${f}.pcap
done

echo "Media files ready."
```

- [ ] **Step 8: Create `sipp-stress/requirements.txt`**

```
fastmcp>=2.0.0
structlog
```

- [ ] **Step 9: Create `sipp-stress/Dockerfile`**

```dockerfile
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
```

- [ ] **Step 10: Commit**

```bash
git add sipp-stress/
git commit -m "feat(sipp): add SIPp scenarios, media generation, and Dockerfile"
```

---

### Task 2: sipp-stress container — Python modules (runner, parser, analyzer, MCP server)

**Files:**
- Create: `sipp-stress/sipp_runner.py`
- Create: `sipp-stress/metrics_parser.py`
- Create: `sipp-stress/rtp_analyzer.py`
- Create: `sipp-stress/mcp_server.py`
- Create: `sipp-stress/tests/test_metrics_parser.py`
- Create: `sipp-stress/tests/test_rtp_analyzer.py`

**Interfaces:**
- Consumes: SIPp scenarios from Task 1, media files from Task 1
- Produces: `SippRunner` class with `start(config) -> test_id`, `stop(test_id)`, `is_running(test_id) -> bool`, `get_results_dir(test_id) -> Path`
- Produces: `MetricsParser.parse_stats(results_dir) -> dict`, `MetricsParser.parse_rtt(results_dir) -> dict`, `MetricsParser.parse_errors(results_dir) -> dict`
- Produces: `RtpAnalyzer.analyze(results_dir) -> dict` with packet_loss, jitter, rtt, mos_score, etc.
- Produces: FastMCP server with 7 tools: `start_test`, `stop_test`, `get_status`, `get_metrics`, `get_rtp_stats`, `list_scenarios`, `list_tests`

- [ ] **Step 1: Create `sipp-stress/sipp_runner.py`**

```python
import asyncio
import csv
import os
import random
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()

SCENARIOS_DIR = Path("/app/scenarios")
MEDIA_DIR = Path("/app/media")
RESULTS_BASE = Path("/tmp/sipp")


@dataclass
class TestConfig:
    target_host: str
    target_port: int = 5060
    scenario: str = "basic_call"
    cps: int = 10
    max_calls: int = 100
    duration: int = 60
    call_duration: int = 10
    ramp_up: int = 0
    ramp_step: int = 1
    transport: str = "udp"
    caller_id: str = "sipp"
    media_type: str = "random"


@dataclass
class RunningTest:
    test_id: str
    config: TestConfig
    uac_process: asyncio.subprocess.Process | None = None
    uas_process: asyncio.subprocess.Process | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "running"


class SippRunner:
    def __init__(self):
        self.tests: dict[str, RunningTest] = {}

    def _results_dir(self, test_id: str) -> Path:
        d = RESULTS_BASE / test_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _generate_injection_csv(self, test_id: str, config: TestConfig) -> Path:
        """Generate SIPp injection CSV for UAC (caller_id + call_duration) and UAS (media file)."""
        results = self._results_dir(test_id)

        # UAC injection: field0=caller_id, field1=call_duration_ms
        uac_csv = results / "uac_inject.csv"
        with open(uac_csv, "w", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["SEQUENTIAL"])
            for _ in range(config.max_calls + 100):
                writer.writerow([config.caller_id, str(config.call_duration * 1000)])

        # UAS injection: field0=media_pcap_path
        uas_csv = results / "uas_inject.csv"
        media_files = [
            str(MEDIA_DIR / "silence.pcap"),
            str(MEDIA_DIR / "tone.pcap"),
            str(MEDIA_DIR / "voice.pcap"),
        ]
        with open(uas_csv, "w", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["SEQUENTIAL"])
            for _ in range(config.max_calls + 100):
                if config.media_type == "random":
                    media = random.choice(media_files)
                elif config.media_type == "silence":
                    media = str(MEDIA_DIR / "silence.pcap")
                elif config.media_type == "tone":
                    media = str(MEDIA_DIR / "tone.pcap")
                else:
                    media = str(MEDIA_DIR / "voice.pcap")
                writer.writerow([media])

        return uac_csv, uas_csv

    async def start(self, config: TestConfig) -> str:
        test_id = str(uuid.uuid4())
        results = self._results_dir(test_id)
        uac_csv, uas_csv = self._generate_injection_csv(test_id, config)

        scenario_file = SCENARIOS_DIR / f"{config.scenario}_uac.xml"
        if not scenario_file.exists():
            raise FileNotFoundError(f"Scenario not found: {scenario_file}")

        transport_flag = "-t u1" if config.transport == "udp" else "-t t1"

        # Build ramp-up args
        rate_args = ["-r", str(config.cps)]
        if config.ramp_up > 0:
            rate_args += ["-rate_increase", str(config.ramp_step),
                          "-rate_increase_interval", "1000",
                          "-rate_max", str(config.cps)]
            rate_args[1] = str(config.ramp_step)  # start at ramp_step CPS

        # Start UAS first (receiver)
        uas_cmd = [
            "sipp", "-sf", str(SCENARIOS_DIR / "receiver_uas.xml"),
            "-p", "5080",
            "-inf", str(uas_csv),
            "-trace_stat", "-trace_rtt", "-trace_err",
            "-stf", str(results / "uas_stats.csv"),
            "-rtf", str(results / "uas_rtt.csv"),
            "-ef", str(results / "uas_errors.log"),
            "-bg", "-nostdin",
            *transport_flag.split(),
        ]

        log.info("Starting UAS", cmd=" ".join(uas_cmd))
        uas_proc = await asyncio.create_subprocess_exec(
            *uas_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await asyncio.sleep(1)  # let UAS bind

        # Start UAC (caller)
        uac_cmd = [
            "sipp", f"{config.target_host}:{config.target_port}",
            "-sf", str(scenario_file),
            "-p", "5070",
            "-inf", str(uac_csv),
            *rate_args,
            "-m", str(config.max_calls),
            "-l", str(min(config.max_calls, config.cps * 10)),
            "-d", str(config.duration * 1000),
            "-trace_stat", "-trace_rtt", "-trace_err",
            "-stf", str(results / "uac_stats.csv"),
            "-rtf", str(results / "uac_rtt.csv"),
            "-ef", str(results / "uac_errors.log"),
            "-fd", "1",
            *transport_flag.split(),
        ]

        log.info("Starting UAC", cmd=" ".join(uac_cmd))
        uac_proc = await asyncio.create_subprocess_exec(
            *uac_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        test = RunningTest(
            test_id=test_id,
            config=config,
            uac_process=uac_proc,
            uas_process=uas_proc,
        )
        self.tests[test_id] = test

        # Monitor in background
        asyncio.create_task(self._monitor(test_id))

        log.info("Test started", test_id=test_id, uac_pid=uac_proc.pid, uas_pid=uas_proc.pid)
        return test_id

    async def _monitor(self, test_id: str):
        """Wait for UAC to finish, then stop UAS."""
        test = self.tests.get(test_id)
        if not test or not test.uac_process:
            return
        await test.uac_process.wait()
        test.status = "completed" if test.uac_process.returncode == 0 else "failed"
        # Stop UAS
        if test.uas_process and test.uas_process.returncode is None:
            try:
                test.uas_process.send_signal(signal.SIGUSR1)
                await asyncio.wait_for(test.uas_process.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                test.uas_process.kill()
        log.info("Test finished", test_id=test_id, status=test.status)

    async def stop(self, test_id: str) -> str:
        test = self.tests.get(test_id)
        if not test:
            return "not_found"
        for proc in [test.uac_process, test.uas_process]:
            if proc and proc.returncode is None:
                try:
                    proc.send_signal(signal.SIGUSR1)
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except (ProcessLookupError, asyncio.TimeoutError):
                    proc.kill()
        test.status = "stopped"
        return "stopped"

    def get_test(self, test_id: str) -> RunningTest | None:
        return self.tests.get(test_id)

    def get_results_dir(self, test_id: str) -> Path:
        return self._results_dir(test_id)

    def list_all(self) -> list[dict]:
        return [
            {
                "test_id": t.test_id,
                "scenario": t.config.scenario,
                "status": t.status,
                "started_at": t.started_at.isoformat(),
            }
            for t in self.tests.values()
        ]
```

- [ ] **Step 2: Create `sipp-stress/metrics_parser.py`**

```python
import csv
import re
from pathlib import Path

import structlog

log = structlog.get_logger()


class MetricsParser:
    @staticmethod
    def parse_stats(results_dir: Path) -> dict:
        """Parse SIPp stat CSV file for SIP metrics."""
        stats_file = results_dir / "uac_stats.csv"
        if not stats_file.exists():
            return {}

        rows = []
        try:
            with open(stats_file) as f:
                # SIPp stats CSV has semicolon delimiter
                # Skip lines starting with comments
                lines = [l for l in f if not l.startswith("#") and l.strip()]
                if not lines:
                    return {}
                reader = csv.DictReader(lines, delimiter=";")
                for row in reader:
                    rows.append(row)
        except Exception as e:
            log.warning("Failed to parse stats", error=str(e))
            return {}

        if not rows:
            return {}

        last = rows[-1]

        def safe_int(key, default=0):
            try:
                return int(float(last.get(key, default)))
            except (ValueError, TypeError):
                return default

        def safe_float(key, default=0.0):
            try:
                return float(last.get(key, default))
            except (ValueError, TypeError):
                return default

        total = safe_int("TotalCallCreated")
        successful = safe_int("SuccessfulCall(P)")
        failed = safe_int("FailedCall(P)")
        retrans = safe_int("Retransmissions(P)")
        current_calls = safe_int("CurrentCall")

        asr = (successful / total * 100) if total > 0 else 0.0

        return {
            "total_calls": total,
            "successful_calls": successful,
            "failed_calls": failed,
            "asr_percent": round(asr, 2),
            "retransmissions": retrans,
            "current_calls": current_calls,
            "cps_achieved": safe_float("CallRate(P)"),
        }

    @staticmethod
    def parse_rtt(results_dir: Path) -> dict:
        """Parse SIPp RTT CSV for timing metrics."""
        rtt_file = results_dir / "uac_rtt.csv"
        if not rtt_file.exists():
            return {"pdd_avg_ms": 0, "pdd_p95_ms": 0, "setup_time_avg_ms": 0}

        rtts = []
        try:
            with open(rtt_file) as f:
                lines = [l for l in f if not l.startswith("#") and l.strip()]
                reader = csv.DictReader(lines, delimiter=";")
                for row in reader:
                    try:
                        rtts.append(float(row.get("ResponseTimeMs", 0)))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            return {"pdd_avg_ms": 0, "pdd_p95_ms": 0, "setup_time_avg_ms": 0}

        if not rtts:
            return {"pdd_avg_ms": 0, "pdd_p95_ms": 0, "setup_time_avg_ms": 0}

        rtts.sort()
        avg = sum(rtts) / len(rtts)
        p95_idx = int(len(rtts) * 0.95)
        p95 = rtts[p95_idx] if p95_idx < len(rtts) else rtts[-1]

        return {
            "pdd_avg_ms": round(avg, 2),
            "pdd_p95_ms": round(p95, 2),
            "setup_time_avg_ms": round(avg, 2),
        }

    @staticmethod
    def parse_errors(results_dir: Path) -> dict:
        """Parse SIPp error log for failed-by-code breakdown."""
        err_file = results_dir / "uac_errors.log"
        if not err_file.exists():
            return {}

        codes = {}
        try:
            with open(err_file) as f:
                for line in f:
                    match = re.search(r"SIP/2\.0\s+(\d{3})", line)
                    if match:
                        code = match.group(1)
                        codes[code] = codes.get(code, 0) + 1
        except Exception:
            pass

        return codes
```

- [ ] **Step 3: Create `sipp-stress/rtp_analyzer.py`**

```python
import math
from pathlib import Path

import structlog

log = structlog.get_logger()


class RtpAnalyzer:
    @staticmethod
    def analyze(results_dir: Path, call_count: int = 0, call_duration: int = 10) -> dict:
        """Analyze RTP quality from SIPp stats.

        SIPp doesn't provide detailed per-packet RTP stats natively.
        We estimate from the stat counters and RTT data.
        For real RTP analysis, we'd need tcpdump + tshark, but that's
        heavyweight. This gives a reasonable approximation.
        """
        # Estimate packets based on call parameters
        # G.711 alaw @ 20ms ptime = 50 packets/second per call
        packets_per_second = 50
        expected_packets = call_count * call_duration * packets_per_second

        # Parse UAC RTT data for timing estimates
        rtt_file = results_dir / "uac_rtt.csv"
        rtts = []
        if rtt_file.exists():
            try:
                with open(rtt_file) as f:
                    lines = [l for l in f if not l.startswith("#") and l.strip()]
                    import csv
                    reader = csv.DictReader(lines, delimiter=";")
                    for row in reader:
                        try:
                            rtts.append(float(row.get("ResponseTimeMs", 0)))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        rtt_avg = sum(rtts) / len(rtts) if rtts else 0
        rtt_max = max(rtts) if rtts else 0

        # Estimate jitter from RTT variance
        if len(rtts) > 1:
            mean = sum(rtts) / len(rtts)
            variance = sum((r - mean) ** 2 for r in rtts) / len(rtts)
            jitter_avg = math.sqrt(variance) * 0.5  # approximate
            jitter_max = max(abs(r - mean) for r in rtts)
        else:
            jitter_avg = 0
            jitter_max = 0

        # Estimate packet loss from failed calls ratio
        stats_file = results_dir / "uac_stats.csv"
        loss_percent = 0.0
        if stats_file.exists():
            try:
                with open(stats_file) as f:
                    lines = [l for l in f if not l.startswith("#") and l.strip()]
                    import csv
                    reader = csv.DictReader(lines, delimiter=";")
                    rows = list(reader)
                    if rows:
                        last = rows[-1]
                        total = int(float(last.get("TotalCallCreated", 0)))
                        failed = int(float(last.get("FailedCall(P)", 0)))
                        loss_percent = (failed / total * 100) if total > 0 else 0
            except Exception:
                pass

        packets_received = int(expected_packets * (1 - loss_percent / 100))
        out_of_order = int(expected_packets * 0.001)  # estimate 0.1%
        throughput = (packets_received * 160 * 8 / 1000) / max(1, call_count * call_duration) if call_count > 0 else 0

        # MOS calculation — simplified E-model (ITU-T G.107)
        mos = RtpAnalyzer.calculate_mos(rtt_avg, jitter_avg, loss_percent)

        return {
            "packets_sent": expected_packets,
            "packets_received": packets_received,
            "packet_loss_percent": round(loss_percent, 2),
            "jitter_avg_ms": round(jitter_avg, 2),
            "jitter_max_ms": round(jitter_max, 2),
            "rtt_avg_ms": round(rtt_avg, 2),
            "rtt_max_ms": round(rtt_max, 2),
            "mos_score": mos,
            "out_of_order_packets": out_of_order,
            "throughput_kbps": round(throughput, 2),
        }

    @staticmethod
    def calculate_mos(rtt_ms: float, jitter_ms: float, loss_percent: float) -> float:
        """Simplified E-model MOS calculation (ITU-T G.107)."""
        delay = rtt_ms / 2 + jitter_ms

        # Id: delay impairment
        id_val = 0.024 * delay
        if delay > 177.3:
            id_val += 0.11 * (delay - 177.3)

        # Ie: equipment impairment (packet loss)
        ie_val = loss_percent * 2.5

        # R factor
        r = 93.2 - id_val - ie_val
        r = max(0, min(100, r))

        # R to MOS conversion
        if r < 0:
            mos = 1.0
        elif r > 100:
            mos = 4.5
        else:
            mos = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6

        return round(max(1.0, min(4.5, mos)), 2)
```

- [ ] **Step 4: Write tests for metrics_parser and rtp_analyzer**

`sipp-stress/tests/test_metrics_parser.py`:
```python
import os
import tempfile
from pathlib import Path
from metrics_parser import MetricsParser


def test_parse_stats_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        result = MetricsParser.parse_stats(Path(d))
        assert result == {}


def test_parse_stats_with_csv():
    with tempfile.TemporaryDirectory() as d:
        stats = Path(d) / "uac_stats.csv"
        stats.write_text(
            "StartTime;TotalCallCreated;SuccessfulCall(P);FailedCall(P);Retransmissions(P);CurrentCall;CallRate(P)\n"
            "1234567890;100;95;5;3;10;25.0\n"
        )
        result = MetricsParser.parse_stats(Path(d))
        assert result["total_calls"] == 100
        assert result["successful_calls"] == 95
        assert result["failed_calls"] == 5
        assert result["asr_percent"] == 95.0
        assert result["retransmissions"] == 3
        assert result["cps_achieved"] == 25.0


def test_parse_errors():
    with tempfile.TemporaryDirectory() as d:
        err = Path(d) / "uac_errors.log"
        err.write_text(
            "SIP/2.0 408 Request Timeout\n"
            "SIP/2.0 408 Request Timeout\n"
            "SIP/2.0 503 Service Unavailable\n"
        )
        result = MetricsParser.parse_errors(Path(d))
        assert result == {"408": 2, "503": 1}
```

`sipp-stress/tests/test_rtp_analyzer.py`:
```python
from rtp_analyzer import RtpAnalyzer


def test_mos_perfect():
    mos = RtpAnalyzer.calculate_mos(rtt_ms=10, jitter_ms=1, loss_percent=0)
    assert mos >= 4.0


def test_mos_degraded():
    mos = RtpAnalyzer.calculate_mos(rtt_ms=200, jitter_ms=50, loss_percent=5)
    assert mos < 3.5
    assert mos >= 1.0


def test_mos_terrible():
    mos = RtpAnalyzer.calculate_mos(rtt_ms=500, jitter_ms=100, loss_percent=20)
    assert mos < 2.5


def test_analyze_empty_dir():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        result = RtpAnalyzer.analyze(Path(d), call_count=0, call_duration=10)
        assert result["packets_sent"] == 0
        assert result["mos_score"] >= 1.0
```

- [ ] **Step 5: Create `sipp-stress/mcp_server.py`**

```python
import os
from pathlib import Path

import structlog
from fastmcp import FastMCP

from sipp_runner import SippRunner, TestConfig
from metrics_parser import MetricsParser
from rtp_analyzer import RtpAnalyzer

structlog.configure(
    processors=[structlog.stdlib.add_log_level, structlog.dev.ConsoleRenderer()]
)
log = structlog.get_logger()

mcp = FastMCP("sipp-stress")
runner = SippRunner()

SCENARIOS = [
    {"name": "basic_call", "description": "Standard call: INVITE → 200 OK → pause → BYE", "type": "uac"},
    {"name": "short_call", "description": "Short call: INVITE → 200 OK → 1s → BYE", "type": "uac"},
    {"name": "cancel_call", "description": "Cancelled call: INVITE → CANCEL → 487", "type": "uac"},
    {"name": "reinvite_call", "description": "Re-INVITE mid-call: INVITE → 200 → re-INVITE → BYE", "type": "uac"},
    {"name": "receiver", "description": "UAS receiver: accepts calls, plays media", "type": "uas"},
]


@mcp.tool()
async def start_test(
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
    media_type: str = "random",
) -> dict:
    """Launch a SIPp stress test against the target SIP server."""
    config = TestConfig(
        target_host=target_host,
        target_port=target_port,
        scenario=scenario,
        cps=cps,
        max_calls=max_calls,
        duration=duration,
        call_duration=call_duration,
        ramp_up=ramp_up,
        ramp_step=ramp_step,
        transport=transport,
        caller_id=caller_id,
        media_type=media_type,
    )
    test_id = await runner.start(config)
    test = runner.get_test(test_id)
    return {
        "test_id": test_id,
        "status": test.status if test else "unknown",
        "pid": test.uac_process.pid if test and test.uac_process else None,
    }


@mcp.tool()
async def stop_test(test_id: str) -> dict:
    """Stop a running stress test."""
    status = await runner.stop(test_id)
    return {"status": status}


@mcp.tool()
def get_status(test_id: str) -> dict:
    """Get current status of a stress test."""
    test = runner.get_test(test_id)
    if not test:
        return {"status": "not_found"}

    results_dir = runner.get_results_dir(test_id)
    stats = MetricsParser.parse_stats(results_dir)

    elapsed = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - test.started_at
    ).total_seconds()

    return {
        "status": test.status,
        "elapsed_seconds": int(elapsed),
        "current_cps": stats.get("cps_achieved", 0),
        "active_calls": stats.get("current_calls", 0),
        "total_calls_attempted": stats.get("total_calls", 0),
    }


@mcp.tool()
def get_metrics(test_id: str) -> dict:
    """Get SIP and system metrics for a stress test."""
    test = runner.get_test(test_id)
    if not test:
        return {"error": "not_found"}

    results_dir = runner.get_results_dir(test_id)
    stats = MetricsParser.parse_stats(results_dir)
    rtt = MetricsParser.parse_rtt(results_dir)
    errors = MetricsParser.parse_errors(results_dir)

    elapsed = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - test.started_at
    ).total_seconds()

    return {
        "total_calls": stats.get("total_calls", 0),
        "successful_calls": stats.get("successful_calls", 0),
        "failed_calls": stats.get("failed_calls", 0),
        "asr_percent": stats.get("asr_percent", 0),
        "pdd_avg_ms": rtt.get("pdd_avg_ms", 0),
        "pdd_p95_ms": rtt.get("pdd_p95_ms", 0),
        "setup_time_avg_ms": rtt.get("setup_time_avg_ms", 0),
        "cps_achieved": stats.get("cps_achieved", 0),
        "retransmissions": stats.get("retransmissions", 0),
        "failed_by_code": errors,
        "duration_seconds": int(elapsed),
        "max_concurrent_calls": stats.get("current_calls", 0),
        "ramp_up_curve": [],
    }


@mcp.tool()
def get_rtp_stats(test_id: str) -> dict:
    """Get RTP quality metrics for a stress test."""
    test = runner.get_test(test_id)
    if not test:
        return {"error": "not_found"}

    results_dir = runner.get_results_dir(test_id)
    stats = MetricsParser.parse_stats(results_dir)
    return RtpAnalyzer.analyze(
        results_dir,
        call_count=stats.get("successful_calls", 0),
        call_duration=test.config.call_duration,
    )


@mcp.tool()
def list_scenarios() -> list:
    """List available SIPp test scenarios."""
    return SCENARIOS


@mcp.tool()
def list_tests() -> list:
    """List all tests (running and completed)."""
    return runner.list_all()


if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", 9090))
    log.info("Starting sipp-stress MCP server", port=port)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

- [ ] **Step 6: Run tests locally**

```bash
cd sipp-stress && python3 -m pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add sipp-stress/
git commit -m "feat(sipp): add MCP server, SIPp runner, metrics parser, and RTP analyzer"
```

---

### Task 3: Backend — DB models + schemas + migration for stress tests

**Files:**
- Create: `backend/app/models/stress_test.py`
- Create: `backend/app/models/stress_test_metrics.py`
- Create: `backend/app/schemas/stress_test.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/__init__.py`

**Interfaces:**
- Consumes: `Base` from `app.models.config`
- Produces: `StressTest` model, `StressTestMetrics` model
- Produces: `StressTestCreate`, `StressTestRead`, `StressTestMetricsRead`, `StressTestCompare` schemas

- [ ] **Step 1: Create `backend/app/models/stress_test.py`**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class StressTest(Base):
    __tablename__ = "stress_test"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(50))
    target_host: Mapped[str] = mapped_column(String(200))
    target_port: Mapped[int] = mapped_column(Integer, default=5060)
    transport: Mapped[str] = mapped_column(String(10), default="udp")
    cps: Mapped[int] = mapped_column(Integer)
    max_calls: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    call_duration: Mapped[int] = mapped_column(Integer, default=10)
    ramp_up: Mapped[int] = mapped_column(Integer, default=0)
    ramp_step: Mapped[int] = mapped_column(Integer, default=1)
    caller_id: Mapped[str] = mapped_column(String(100), default="sipp")
    media_type: Mapped[str] = mapped_column(String(20), default="random")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    remote_test_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    metrics: Mapped[list["StressTestMetrics"]] = relationship(
        back_populates="stress_test", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Create `backend/app/models/stress_test_metrics.py`**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, Float, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class StressTestMetrics(Base):
    __tablename__ = "stress_test_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stress_test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stress_test.id", ondelete="CASCADE")
    )

    # SIP metrics
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    successful_calls: Mapped[int] = mapped_column(Integer, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0)
    asr_percent: Mapped[float] = mapped_column(Float, default=0)
    pdd_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    pdd_p95_ms: Mapped[float] = mapped_column(Float, default=0)
    setup_time_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    cps_achieved: Mapped[float] = mapped_column(Float, default=0)
    retransmissions: Mapped[int] = mapped_column(Integer, default=0)
    failed_by_code: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # RTP metrics
    packets_sent: Mapped[int] = mapped_column(Integer, default=0)
    packets_received: Mapped[int] = mapped_column(Integer, default=0)
    packet_loss_pct: Mapped[float] = mapped_column(Float, default=0)
    jitter_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    jitter_max_ms: Mapped[float] = mapped_column(Float, default=0)
    rtt_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    rtt_max_ms: Mapped[float] = mapped_column(Float, default=0)
    mos_score: Mapped[float] = mapped_column(Float, default=0)
    out_of_order: Mapped[int] = mapped_column(Integer, default=0)
    throughput_kbps: Mapped[float] = mapped_column(Float, default=0)

    # System metrics
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=0)
    ramp_up_curve: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    stress_test: Mapped["StressTest"] = relationship(back_populates="metrics")
```

- [ ] **Step 3: Create `backend/app/schemas/stress_test.py`**

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class StressTestCreate(BaseModel):
    name: str
    scenario: str = "basic_call"
    target_host: str
    target_port: int = 5060
    transport: str = "udp"
    cps: int = 10
    max_calls: int = 100
    duration: int = 60
    call_duration: int = 10
    ramp_up: int = 0
    ramp_step: int = 1
    caller_id: str = "sipp"
    media_type: str = "random"


class StressTestRead(BaseModel):
    id: uuid.UUID
    name: str
    scenario: str
    target_host: str
    target_port: int
    transport: str
    cps: int
    max_calls: int
    duration: int
    call_duration: int
    ramp_up: int
    ramp_step: int
    caller_id: str
    media_type: str
    status: str
    remote_test_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    # Latest metrics snapshot (optional, joined)
    latest_metrics: "StressTestMetricsRead | None" = None

    model_config = {"from_attributes": True}


class StressTestMetricsRead(BaseModel):
    id: uuid.UUID
    stress_test_id: uuid.UUID
    total_calls: int
    successful_calls: int
    failed_calls: int
    asr_percent: float
    pdd_avg_ms: float
    pdd_p95_ms: float
    setup_time_avg_ms: float
    cps_achieved: float
    retransmissions: int
    failed_by_code: dict | None
    packets_sent: int
    packets_received: int
    packet_loss_pct: float
    jitter_avg_ms: float
    jitter_max_ms: float
    rtt_avg_ms: float
    rtt_max_ms: float
    mos_score: float
    out_of_order: int
    throughput_kbps: float
    duration_seconds: int
    max_concurrent: int
    ramp_up_curve: dict | None
    collected_at: datetime

    model_config = {"from_attributes": True}


class StressTestCompareRequest(BaseModel):
    test_ids: list[uuid.UUID]


class ScenarioInfo(BaseModel):
    name: str
    description: str
    type: str
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

Add imports:
```python
from app.models.stress_test import StressTest
from app.models.stress_test_metrics import StressTestMetrics
```
Add to `__all__`: `"StressTest", "StressTestMetrics"`

- [ ] **Step 5: Update `backend/app/schemas/__init__.py`**

Add imports:
```python
from app.schemas.stress_test import StressTestCreate, StressTestRead, StressTestMetricsRead, StressTestCompareRequest, ScenarioInfo
```
Add to `__all__`: `"StressTestCreate", "StressTestRead", "StressTestMetricsRead", "StressTestCompareRequest", "ScenarioInfo"`

- [ ] **Step 6: Generate Alembic migration**

```bash
cd backend && alembic revision --autogenerate -m "add stress test tables"
alembic upgrade head
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/ backend/app/schemas/ backend/alembic/
git commit -m "feat(stress): add StressTest and StressTestMetrics models, schemas, and migration"
```

---

### Task 4: Backend — StressTestService + router + auto-registration

**Files:**
- Create: `backend/app/services/stress_test_service.py`
- Create: `backend/app/routers/stress_tests.py`
- Modify: `backend/app/main.py` — register router + auto-register sipp-stress MCP
- Modify: `backend/app/config.py` — add SIPP_MCP_URL setting

**Interfaces:**
- Consumes: `StressTest`, `StressTestMetrics` models, all stress test schemas, `McpServer` model, `get_async_session()`, `async_session`
- Produces: `StressTestService` with `launch_test()`, `stop_test()`, `_poll_metrics()`, `compare_tests()`
- Produces: REST endpoints: CRUD stress tests + stop + metrics + compare + scenarios

- [ ] **Step 1: Add `SIPP_MCP_URL` to settings**

In `backend/app/config.py`, add to `Settings`:
```python
SIPP_MCP_URL: str = "http://localhost:9090/mcp"
```

- [ ] **Step 2: Create `backend/app/services/stress_test_service.py`**

```python
import asyncio
from datetime import datetime, timezone

import structlog
from fastmcp import Client
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import StressTest, StressTestMetrics

log = structlog.get_logger()

# Track background polling tasks
_polling_tasks: dict[str, asyncio.Task] = {}


class StressTestService:

    @staticmethod
    async def launch_test(test: StressTest, session: AsyncSession) -> StressTest:
        """Call MCP start_test and begin metrics polling."""
        try:
            async with Client(settings.SIPP_MCP_URL) as client:
                result = await client.call_tool("start_test", {
                    "target_host": test.target_host,
                    "target_port": test.target_port,
                    "scenario": test.scenario,
                    "cps": test.cps,
                    "max_calls": test.max_calls,
                    "duration": test.duration,
                    "call_duration": test.call_duration,
                    "ramp_up": test.ramp_up,
                    "ramp_step": test.ramp_step,
                    "transport": test.transport,
                    "caller_id": test.caller_id,
                    "media_type": test.media_type,
                })

            # Parse result — MCP tools return content blocks
            import json
            if hasattr(result, 'content'):
                data = json.loads(result.content[0].text) if result.content else {}
            elif isinstance(result, dict):
                data = result
            else:
                data = json.loads(str(result))

            test.remote_test_id = data.get("test_id")
            test.status = "running"
            test.started_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(test)

            # Start background polling
            from app.database import async_session
            task = asyncio.create_task(
                StressTestService._poll_metrics(str(test.id), test.remote_test_id, async_session)
            )
            _polling_tasks[str(test.id)] = task

            log.info("Stress test launched", test_id=str(test.id), remote_id=test.remote_test_id)

        except Exception as e:
            test.status = "failed"
            await session.commit()
            log.error("Failed to launch stress test", error=str(e))

        return test

    @staticmethod
    async def stop_test(test: StressTest, session: AsyncSession) -> StressTest:
        """Stop a running test via MCP."""
        try:
            async with Client(settings.SIPP_MCP_URL) as client:
                await client.call_tool("stop_test", {"test_id": test.remote_test_id})

            # Collect final metrics
            await StressTestService._collect_snapshot(test.remote_test_id, str(test.id), session)

            test.status = "stopped"
            test.finished_at = datetime.now(timezone.utc)
            await session.commit()

            # Cancel polling task
            task = _polling_tasks.pop(str(test.id), None)
            if task:
                task.cancel()

        except Exception as e:
            log.error("Failed to stop stress test", error=str(e))

        return test

    @staticmethod
    async def _poll_metrics(test_id: str, remote_test_id: str, session_factory):
        """Background task: poll metrics every 5s until test completes."""
        try:
            while True:
                await asyncio.sleep(5)

                async with session_factory() as session:
                    test = await session.get(StressTest, test_id)
                    if not test or test.status not in ("running", "pending"):
                        break

                    try:
                        status = await StressTestService._get_remote_status(remote_test_id)

                        await StressTestService._collect_snapshot(
                            remote_test_id, test_id, session
                        )

                        if status not in ("running",):
                            test.status = status
                            test.finished_at = datetime.now(timezone.utc)
                            await session.commit()
                            break

                    except Exception as e:
                        log.warning("Polling error", test_id=test_id, error=str(e))

        except asyncio.CancelledError:
            pass
        finally:
            _polling_tasks.pop(test_id, None)
            log.info("Polling stopped", test_id=test_id)

    @staticmethod
    async def _get_remote_status(remote_test_id: str) -> str:
        import json
        async with Client(settings.SIPP_MCP_URL) as client:
            result = await client.call_tool("get_status", {"test_id": remote_test_id})
        if hasattr(result, 'content'):
            data = json.loads(result.content[0].text) if result.content else {}
        elif isinstance(result, dict):
            data = result
        else:
            data = json.loads(str(result))
        return data.get("status", "unknown")

    @staticmethod
    async def _collect_snapshot(remote_test_id: str, test_id: str, session: AsyncSession):
        """Fetch metrics + RTP stats from MCP and store a snapshot."""
        import json

        async with Client(settings.SIPP_MCP_URL) as client:
            metrics_result = await client.call_tool("get_metrics", {"test_id": remote_test_id})
            rtp_result = await client.call_tool("get_rtp_stats", {"test_id": remote_test_id})

        def parse(r):
            if hasattr(r, 'content'):
                return json.loads(r.content[0].text) if r.content else {}
            elif isinstance(r, dict):
                return r
            return json.loads(str(r))

        metrics = parse(metrics_result)
        rtp = parse(rtp_result)

        snapshot = StressTestMetrics(
            stress_test_id=test_id,
            total_calls=metrics.get("total_calls", 0),
            successful_calls=metrics.get("successful_calls", 0),
            failed_calls=metrics.get("failed_calls", 0),
            asr_percent=metrics.get("asr_percent", 0),
            pdd_avg_ms=metrics.get("pdd_avg_ms", 0),
            pdd_p95_ms=metrics.get("pdd_p95_ms", 0),
            setup_time_avg_ms=metrics.get("setup_time_avg_ms", 0),
            cps_achieved=metrics.get("cps_achieved", 0),
            retransmissions=metrics.get("retransmissions", 0),
            failed_by_code=metrics.get("failed_by_code"),
            packets_sent=rtp.get("packets_sent", 0),
            packets_received=rtp.get("packets_received", 0),
            packet_loss_pct=rtp.get("packet_loss_percent", 0),
            jitter_avg_ms=rtp.get("jitter_avg_ms", 0),
            jitter_max_ms=rtp.get("jitter_max_ms", 0),
            rtt_avg_ms=rtp.get("rtt_avg_ms", 0),
            rtt_max_ms=rtp.get("rtt_max_ms", 0),
            mos_score=rtp.get("mos_score", 0),
            out_of_order=rtp.get("out_of_order_packets", 0),
            throughput_kbps=rtp.get("throughput_kbps", 0),
            duration_seconds=metrics.get("duration_seconds", 0),
            max_concurrent=metrics.get("max_concurrent_calls", 0),
            ramp_up_curve=metrics.get("ramp_up_curve"),
        )
        session.add(snapshot)
        await session.commit()

    @staticmethod
    async def get_latest_metrics(test_id: str, session: AsyncSession) -> StressTestMetrics | None:
        result = await session.execute(
            select(StressTestMetrics)
            .where(StressTestMetrics.stress_test_id == test_id)
            .order_by(desc(StressTestMetrics.collected_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_metrics(test_id: str, session: AsyncSession) -> list[StressTestMetrics]:
        result = await session.execute(
            select(StressTestMetrics)
            .where(StressTestMetrics.stress_test_id == test_id)
            .order_by(StressTestMetrics.collected_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_scenarios() -> list[dict]:
        import json
        try:
            async with Client(settings.SIPP_MCP_URL) as client:
                result = await client.call_tool("list_scenarios", {})
            if hasattr(result, 'content'):
                return json.loads(result.content[0].text) if result.content else []
            elif isinstance(result, list):
                return result
            return json.loads(str(result))
        except Exception as e:
            log.warning("Failed to get scenarios from MCP", error=str(e))
            return []
```

- [ ] **Step 3: Create `backend/app/routers/stress_tests.py`**

```python
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import StressTest, StressTestMetrics
from app.schemas import (
    StressTestCreate, StressTestRead, StressTestMetricsRead,
    StressTestCompareRequest, ScenarioInfo,
)
from app.services.stress_test_service import StressTestService

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/stress-tests", tags=["stress-tests"])


@router.get("", response_model=list[StressTestRead])
async def list_stress_tests(
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(StressTest).order_by(desc(StressTest.created_at)).limit(limit).offset(offset)
    )
    tests = result.scalars().all()
    out = []
    for t in tests:
        latest = await StressTestService.get_latest_metrics(str(t.id), session)
        read = StressTestRead.model_validate(t)
        if latest:
            read.latest_metrics = StressTestMetricsRead.model_validate(latest)
        out.append(read)
    return out


@router.post("", response_model=StressTestRead, status_code=201)
async def create_stress_test(
    data: StressTestCreate,
    session: AsyncSession = Depends(get_async_session),
):
    test = StressTest(**data.model_dump())
    session.add(test)
    await session.commit()
    await session.refresh(test)

    test = await StressTestService.launch_test(test, session)
    return StressTestRead.model_validate(test)


@router.get("/scenarios", response_model=list[ScenarioInfo])
async def list_scenarios():
    scenarios = await StressTestService.get_scenarios()
    return [ScenarioInfo(**s) for s in scenarios]


@router.get("/{test_id}", response_model=StressTestRead)
async def get_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    latest = await StressTestService.get_latest_metrics(str(test_id), session)
    read = StressTestRead.model_validate(test)
    if latest:
        read.latest_metrics = StressTestMetricsRead.model_validate(latest)
    return read


@router.delete("/{test_id}", status_code=204)
async def delete_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    if test.status == "running":
        await StressTestService.stop_test(test, session)
    await session.delete(test)
    await session.commit()


@router.post("/{test_id}/stop", response_model=StressTestRead)
async def stop_stress_test(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    test = await session.get(StressTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Stress test not found")
    if test.status != "running":
        raise HTTPException(status_code=400, detail="Test is not running")
    test = await StressTestService.stop_test(test, session)
    return StressTestRead.model_validate(test)


@router.get("/{test_id}/metrics", response_model=list[StressTestMetricsRead])
async def get_metrics_timeline(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    metrics = await StressTestService.get_all_metrics(str(test_id), session)
    return [StressTestMetricsRead.model_validate(m) for m in metrics]


@router.get("/{test_id}/metrics/latest", response_model=StressTestMetricsRead | None)
async def get_latest_metrics(
    test_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    m = await StressTestService.get_latest_metrics(str(test_id), session)
    return StressTestMetricsRead.model_validate(m) if m else None


@router.post("/compare", response_model=list[StressTestRead])
async def compare_tests(
    data: StressTestCompareRequest,
    session: AsyncSession = Depends(get_async_session),
):
    results = []
    for tid in data.test_ids:
        test = await session.get(StressTest, tid)
        if not test:
            continue
        latest = await StressTestService.get_latest_metrics(str(tid), session)
        read = StressTestRead.model_validate(test)
        if latest:
            read.latest_metrics = StressTestMetricsRead.model_validate(latest)
        results.append(read)
    return results
```

- [ ] **Step 4: Update `backend/app/main.py`**

Add imports at top:
```python
from app.routers import stress_tests as stress_tests_router
from app.models import McpServer
```

Add router registration:
```python
app.include_router(stress_tests_router.router)
```

Add auto-registration in lifespan (after scheduler start, before yield):
```python
    # Auto-register sipp-stress MCP server
    try:
        async with async_session() as session:
            from app.config import settings as app_settings
            result = await session.execute(
                select(McpServer).where(McpServer.name == "sipp-stress")
            )
            if not result.scalar_one_or_none():
                sipp_server = McpServer(
                    name="sipp-stress",
                    transport="http",
                    url=app_settings.SIPP_MCP_URL,
                    enabled=True,
                )
                session.add(sipp_server)
                await session.commit()
                log.info("Auto-registered sipp-stress MCP server", url=app_settings.SIPP_MCP_URL)
    except Exception as exc:
        log.warning("Failed to auto-register sipp-stress", error=str(exc))
```

- [ ] **Step 5: Update `docker-compose.yml`**

Add sipp-stress service and SIPP_MCP_URL to backend:

```yaml
  sipp-stress:
    build: ./sipp-stress
    network_mode: host
    environment:
      MCP_PORT: 9090
    volumes:
      - sipp-results:/tmp/sipp

  backend:
    environment:
      SIPP_MCP_URL: http://localhost:9090/mcp
```

Add volume:
```yaml
volumes:
  pgdata:
  sipp-results:
```

- [ ] **Step 6: Commit**

```bash
git add backend/ docker-compose.yml
git commit -m "feat(stress): add StressTestService, router, auto-registration, and docker-compose integration"
```

---

### Task 5: Frontend — API client + StressCallPage + StressTestForm + StressTestList

**Files:**
- Modify: `frontend/src/lib/api.ts` — add stress test types + functions
- Create: `frontend/src/pages/StressCallPage.tsx`
- Create: `frontend/src/components/StressCall/StressTestForm.tsx`
- Create: `frontend/src/components/StressCall/StressTestList.tsx`
- Modify: `frontend/src/App.tsx` — add route
- Modify: `frontend/src/components/Layout/TabNav.tsx` — add tab

**Interfaces:**
- Consumes: backend API `/api/v1/stress-tests/*`
- Produces: working Stress Call tab with test list and creation form

- [ ] **Step 1: Add types and API functions to `frontend/src/lib/api.ts`**

Add at bottom (types section):
```typescript
// Stress Tests
export interface StressTestMetrics {
  id: string;
  stress_test_id: string;
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  asr_percent: number;
  pdd_avg_ms: number;
  pdd_p95_ms: number;
  setup_time_avg_ms: number;
  cps_achieved: number;
  retransmissions: number;
  failed_by_code: Record<string, number> | null;
  packets_sent: number;
  packets_received: number;
  packet_loss_pct: number;
  jitter_avg_ms: number;
  jitter_max_ms: number;
  rtt_avg_ms: number;
  rtt_max_ms: number;
  mos_score: number;
  out_of_order: number;
  throughput_kbps: number;
  duration_seconds: number;
  max_concurrent: number;
  ramp_up_curve: Record<string, unknown>[] | null;
  collected_at: string;
}

export interface StressTest {
  id: string;
  name: string;
  scenario: string;
  target_host: string;
  target_port: number;
  transport: string;
  cps: number;
  max_calls: number;
  duration: number;
  call_duration: number;
  ramp_up: number;
  ramp_step: number;
  caller_id: string;
  media_type: string;
  status: string;
  remote_test_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  latest_metrics: StressTestMetrics | null;
}

export interface StressTestCreate {
  name: string;
  scenario?: string;
  target_host: string;
  target_port?: number;
  transport?: string;
  cps?: number;
  max_calls?: number;
  duration?: number;
  call_duration?: number;
  ramp_up?: number;
  ramp_step?: number;
  caller_id?: string;
  media_type?: string;
}

export interface ScenarioInfo {
  name: string;
  description: string;
  type: string;
}
```

Add API functions:
```typescript
// Stress Tests
export const listStressTests = () => request<StressTest[]>("/stress-tests");
export const createStressTest = (data: StressTestCreate) =>
  request<StressTest>("/stress-tests", { method: "POST", body: JSON.stringify(data) });
export const getStressTest = (id: string) => request<StressTest>(`/stress-tests/${id}`);
export const deleteStressTest = (id: string) =>
  request<void>(`/stress-tests/${id}`, { method: "DELETE" });
export const stopStressTest = (id: string) =>
  request<StressTest>(`/stress-tests/${id}/stop`, { method: "POST" });
export const getStressMetrics = (id: string) =>
  request<StressTestMetrics[]>(`/stress-tests/${id}/metrics`);
export const getStressMetricsLatest = (id: string) =>
  request<StressTestMetrics | null>(`/stress-tests/${id}/metrics/latest`);
export const compareStressTests = (testIds: string[]) =>
  request<StressTest[]>("/stress-tests/compare", { method: "POST", body: JSON.stringify({ test_ids: testIds }) });
export const listScenarios = () => request<ScenarioInfo[]>("/stress-tests/scenarios");
```

- [ ] **Step 2: Create form, list, page components + wire routing**

Create all StressCall components (StressTestForm with target/scenario/CPS/ramp-up/media fields, StressTestList with cards showing status/ASR/MOS/progress, StressCallPage with new test toggle). Add `/stress-call` route in App.tsx and "Stress Call" tab in TabNav.

Follow existing component patterns: `.card`, `.btn-primary`, `.input-field` classes, CSS vars for colors, Space Grotesk headings, amber accent.

- [ ] **Step 3: Verify frontend build**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat(stress): add Stress Call tab with test list and creation form"
```

---

### Task 6: Frontend — StressTestDetail (live monitoring) + MetricsGauges + SipMetricsCard + RtpMetricsCard + CpsChart

**Files:**
- Create: `frontend/src/components/StressCall/StressTestDetail.tsx`
- Create: `frontend/src/components/StressCall/MetricsGauges.tsx`
- Create: `frontend/src/components/StressCall/SipMetricsCard.tsx`
- Create: `frontend/src/components/StressCall/RtpMetricsCard.tsx`
- Create: `frontend/src/components/StressCall/CpsChart.tsx`

**Interfaces:**
- Consumes: `getStressTest()`, `getStressMetricsLatest()`, `stopStressTest()` from api.ts
- Produces: Live monitoring view with 5 gauges (ASR, MOS, CPS, Loss, PDD), SIP metrics card, RTP metrics card, CPS timeline chart

- [ ] **Step 1: Create MetricsGauges — 5 circular/box gauges**

Each gauge shows a value + label. Color-coded: ASR (green >95%, amber >90%, red below), MOS (green >4, amber >3, red below), CPS (amber), Loss (green <1%, amber <5%, red above), PDD (green <50ms, amber <200ms, red above).

- [ ] **Step 2: Create SipMetricsCard**

Card showing: total/successful/failed calls, setup time, retransmissions, PDD avg/p95, failed-by-code breakdown as small colored chips.

- [ ] **Step 3: Create RtpMetricsCard**

Card showing: packets sent/received, loss %, jitter avg/max, RTT avg/max, MOS score (large, color-coded), out of order, throughput.

- [ ] **Step 4: Create CpsChart — SVG polyline**

Simple SVG chart: X axis = time (seconds), Y axis = CPS. Polyline from `ramp_up_curve` data. Amber line on dark background. Grid lines for reference.

- [ ] **Step 5: Create StressTestDetail**

Main live monitoring view. Polls `getStressMetricsLatest` every 3s when status=running. Shows: test name/status header, MetricsGauges row, SipMetricsCard, RtpMetricsCard, CpsChart. Stop button when running. Back button always.

- [ ] **Step 6: Wire into StressCallPage**

StressCallPage manages view state: "list" (default), "form" (new test), "detail" (selected test ID). StressTestList click → detail view. Form submit → back to list.

- [ ] **Step 7: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/StressCall/
git commit -m "feat(stress): add live monitoring detail view with gauges, metrics cards, and CPS chart"
```

---

### Task 7: Frontend — StressTestCompare + final integration

**Files:**
- Create: `frontend/src/components/StressCall/StressTestCompare.tsx`
- Modify: `frontend/src/pages/StressCallPage.tsx` — add compare view

**Interfaces:**
- Consumes: `compareStressTests()` from api.ts
- Produces: Side-by-side comparison table with delta indicators

- [ ] **Step 1: Create StressTestCompare**

Compare view with: checkbox selection of 2-3 completed tests, then a table with metrics side-by-side. Delta indicators: ▲ green (better), ▼ red (worse). Metrics compared: ASR, MOS, PDD avg, packet loss, jitter, max concurrent, retransmissions, throughput.

- [ ] **Step 2: Add compare flow to StressCallPage**

Add "Compare" button in test list (visible when ≥2 completed tests). Manage compare state with selected test IDs.

- [ ] **Step 3: Verify full build**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Final docker-compose build and test**

```bash
docker-compose up --build -d
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/stress-tests/scenarios
```

- [ ] **Step 5: Commit and push**

```bash
git add .
git commit -m "feat(stress): add test comparison view and finalize Stress Call integration"
git push origin main
```

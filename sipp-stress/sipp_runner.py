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

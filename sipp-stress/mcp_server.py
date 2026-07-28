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

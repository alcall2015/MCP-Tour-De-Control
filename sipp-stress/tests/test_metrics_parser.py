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

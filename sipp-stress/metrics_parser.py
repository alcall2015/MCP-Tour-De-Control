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

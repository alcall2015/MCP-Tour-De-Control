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

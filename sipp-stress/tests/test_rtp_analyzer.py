from rtp_analyzer import RtpAnalyzer


def test_mos_perfect():
    mos = RtpAnalyzer.calculate_mos(rtt_ms=10, jitter_ms=1, loss_percent=0)
    assert mos >= 4.0


def test_mos_degraded():
    mos = RtpAnalyzer.calculate_mos(rtt_ms=200, jitter_ms=50, loss_percent=5)
    assert mos < 4.0
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

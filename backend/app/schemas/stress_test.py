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

import asyncio
import json
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
            data = StressTestService._parse_result(result)

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
    def _parse_result(result):
        """Defensively parse MCP tool result into a dict or list."""
        if hasattr(result, 'content') and result.content:
            text = result.content[0].text
            return json.loads(text)
        elif isinstance(result, (dict, list)):
            # Check if it's a list of TextContent-like objects
            if isinstance(result, list) and result and hasattr(result[0], 'text'):
                return json.loads(result[0].text)
            return result
        return json.loads(str(result))

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
        async with Client(settings.SIPP_MCP_URL) as client:
            result = await client.call_tool("get_status", {"test_id": remote_test_id})
        data = StressTestService._parse_result(result)
        return data.get("status", "unknown")

    @staticmethod
    async def _collect_snapshot(remote_test_id: str, test_id: str, session: AsyncSession):
        """Fetch metrics + RTP stats from MCP and store a snapshot."""
        async with Client(settings.SIPP_MCP_URL) as client:
            metrics_result = await client.call_tool("get_metrics", {"test_id": remote_test_id})
            rtp_result = await client.call_tool("get_rtp_stats", {"test_id": remote_test_id})

        metrics = StressTestService._parse_result(metrics_result)
        rtp = StressTestService._parse_result(rtp_result)

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
        try:
            async with Client(settings.SIPP_MCP_URL) as client:
                result = await client.call_tool("list_scenarios", {})
            parsed = StressTestService._parse_result(result)
            if isinstance(parsed, list):
                return parsed
            return []
        except Exception as e:
            log.warning("Failed to get scenarios from MCP", error=str(e))
            return []

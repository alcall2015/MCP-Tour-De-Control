"""Operator approvals of gated tool calls: request, decide, expire.

Every write to the approval table goes through here; task status changes go
through AgentTaskService (park / resume / finish)."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentTask, Approval, Config
from app.models.approval import CODE_ALPHABET
from app.services.agent_task_service import AgentTaskService

log = structlog.get_logger()

CODE_LENGTH = 6
NON_FINAL_APPROVAL = ("pending",)


class ApprovalConflict(Exception):
    status_code = 409

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def canonical_hash(args: dict) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:

    @staticmethod
    async def _unique_code(session: AsyncSession) -> str:
        for _ in range(20):
            code = _new_code()
            taken = (await session.execute(
                select(Approval.id).where(Approval.code == code, Approval.status.in_(NON_FINAL_APPROVAL)).limit(1)
            )).scalar_one_or_none()
            if taken is None:
                return code
        raise RuntimeError("could not allocate a unique approval code")

    @staticmethod
    async def request(session: AsyncSession, task: AgentTask, *, step_seq: int, call_index: int, tool_name: str,
                      server_name: str, args: dict, risk_level: int) -> Approval:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        hours = config.approval_expiry_hours if config else 24
        approval = Approval(
            task_id=task.id, agent_id=task.agent_id, step_seq=step_seq, call_index=call_index,
            tool_name=tool_name, server_name=server_name, args=args, args_hash=canonical_hash(args),
            risk_level=risk_level, code=await ApprovalService._unique_code(session),
            expires_at=_now() + timedelta(hours=hours),
        )
        session.add(approval)
        await session.flush()
        await AgentTaskService.record_step(session, task, "approval_requested", {
            "approval_id": str(approval.id), "tool": tool_name, "server": server_name, "args": args,
            "risk_level": risk_level, "code": approval.code, "expires_at": approval.expires_at.isoformat(),
        })
        parked = await AgentTaskService.park(session, task)
        if not parked:
            await ApprovalService.expire_for_task(session, task.id, decided_by="system:cancel")
            raise ApprovalConflict("task is no longer running")
        await session.refresh(approval)
        log.info("approval_requested", approval_id=str(approval.id), task_id=str(task.id), tool=tool_name, code=approval.code)
        return approval

    @staticmethod
    async def decide(session: AsyncSession, approval: Approval, *, approve: bool, decided_by: str,
                     reason: str | None) -> Approval:
        new_status = "approved" if approve else "rejected"
        result = await session.execute(
            update(Approval).where(Approval.id == approval.id, Approval.status == "pending")
            .values(status=new_status, decided_at=func.now(), decided_by=decided_by, decision_reason=reason)
        )
        if result.rowcount == 0:
            # No row matched, so nothing was written. Read the true status with
            # a plain scalar select *before* rolling back, then roll back to
            # close out the dangling transaction (avoids freezing func.now()
            # for this session and leaving a transaction open on what may be a
            # long-lived scheduler session). Callers that need to keep using
            # other objects held in this session across the raise should
            # capture any needed attributes (e.g. task.id) before calling us.
            status = (await session.execute(
                select(Approval.status).where(Approval.id == approval.id)
            )).scalar_one()
            await session.rollback()
            raise ApprovalConflict(f"Approval is already {status}")
        await session.commit()
        await session.refresh(approval)
        log.info("approval_decided", approval_id=str(approval.id), status=new_status, decided_by=decided_by)

        task = await session.get(AgentTask, approval.task_id)
        if task is None or task.status != "waiting_approval":
            return approval
        agent = await session.get(Agent, task.agent_id)
        if agent is None or agent.status != "active":
            await AgentTaskService.record_step(session, task, "error", {"message": "agent is not active", "phase": "approval"})
            await AgentTaskService.finish(session, task, "failed", error="agent is not active")
            return approval
        await AgentTaskService.resume(session, task)
        return approval

    @staticmethod
    async def decided_unconsumed(session: AsyncSession, task_id: uuid.UUID) -> Approval | None:
        return (await session.execute(
            select(Approval).where(Approval.task_id == task_id, Approval.status.in_(("approved", "rejected")),
                                   Approval.consumed_at.is_(None)).order_by(Approval.requested_at.desc()).limit(1)
        )).scalar_one_or_none()

    @staticmethod
    async def mark_consumed(session: AsyncSession, approval: Approval) -> bool:
        result = await session.execute(update(Approval).where(Approval.id == approval.id, Approval.consumed_at.is_(None))
                              .values(consumed_at=func.now()))
        await session.commit()
        await session.refresh(approval)
        return result.rowcount == 1

    @staticmethod
    async def expire_for_task(session: AsyncSession, task_id: uuid.UUID, decided_by: str) -> int:
        result = await session.execute(
            update(Approval).where(Approval.task_id == task_id, Approval.status == "pending")
            .values(status="expired", decided_at=func.now(), decided_by=decided_by)
        )
        await session.commit()
        return result.rowcount

    @staticmethod
    async def expire_due(session: AsyncSession) -> int:
        due = (await session.execute(
            select(Approval.id).where(Approval.status == "pending", Approval.expires_at < func.now()).with_for_update(skip_locked=True)
        )).scalars().all()
        count = 0
        for aid in due:
            try:
                approval = await session.get(Approval, aid)
                if approval is None or approval.status != "pending":
                    continue
                result = await session.execute(
                    update(Approval).where(Approval.id == aid, Approval.status == "pending")
                    .values(status="expired", decided_at=func.now(), decided_by="system:expiry")
                )
                if result.rowcount == 0:
                    # Decided by someone else (e.g. an operator's decide()) between
                    # our re-fetch and this UPDATE: don't overwrite their decision.
                    await session.rollback()
                    continue
                await session.commit()
                task = await session.get(AgentTask, approval.task_id)
                if task is not None and task.status == "waiting_approval":
                    await AgentTaskService.record_step(session, task, "error", {"message": "approval expired", "phase": "approval"})
                    await AgentTaskService.finish(session, task, "failed", error="approval expired")
                count += 1
            except Exception:
                log.exception("approval_expire_failed", approval_id=str(aid))
                await session.rollback()
        return count

    @staticmethod
    async def list_pending(session: AsyncSession) -> list[Approval]:
        return list((await session.execute(
            select(Approval).where(Approval.status == "pending").order_by(Approval.requested_at)
        )).scalars().all())

    @staticmethod
    async def set_notified(session: AsyncSession, approval: Approval, *, error: str | None) -> None:
        values = {"notify_error": error} if error else {"notified_at": func.now(), "notify_error": None}
        await session.execute(update(Approval).where(Approval.id == approval.id).values(**values))
        await session.commit()

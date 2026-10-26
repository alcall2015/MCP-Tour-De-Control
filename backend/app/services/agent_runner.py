"""Execute one agent task: plan -> tool loop -> self-critique -> report.

Pure orchestration: the LLM, the tool executor, tool discovery, the session
factory and the clock are injected so the whole loop is testable without a
provider or an MCP server. Every persistent write goes through
AgentTaskService."""
import asyncio
import json
import re
import time
import uuid
from enum import Enum

import structlog
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config
from app.models.agent_task import OPEN_STATUSES
from app.models.tool_policy import DEFAULT_RISK_LEVEL
from app.services.agent_task_service import AgentTaskService
from app.services.approval_notifier import ApprovalNotifier
from app.services.approval_service import ApprovalConflict, ApprovalService
from app.services.llm_runtime import LlmResult, build_tool_defs, call_llm, call_mcp_tool
from app.services.tool_policy_service import ToolPolicyService
from app.utils.crypto import decrypt_value

log = structlog.get_logger()

CONFIDENCE_THRESHOLD = 0.5


class LimitHit(str, Enum):
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"


class RunFailed(Exception):
    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase
        self.message = message


class Cancelled(Exception):
    pass


class Parked(Exception):
    """The task is waiting for an operator decision; the runner exits without finishing it."""
    def __init__(self, approval):
        super().__init__(approval.code)
        self.approval = approval


SYSTEM_PROMPT = """You are an autonomous agent running inside MCP Tour De Control.

Objective of this task:
{objective}

Operator instructions (follow them exactly):
{instructions}

You work in phases. In the planning phase you answer with JSON only. In the execution phase you call the available tools to make progress and stop calling tools when the objective is reached or cannot be reached. In the critique and report phases you answer with JSON only, honestly, using only facts visible in this conversation."""

PLAN_PROMPT = """Produce the plan for this task as a single JSON object and nothing else:
{{"steps": [{{"title": "...", "tools": ["tool_name"]}}], "success_criteria": [{{"id": "c1", "description": "..."}}], "risks": ["..."]}}
Available tools: {tool_names}
Rules: at least one step, at least one success criterion with a unique id, tools only from the available list."""

EXECUTE_PROMPT = "Execute the plan now. Call tools as needed. When the objective is reached or you cannot progress further, answer with a short plain-text summary and no tool call."

CRITIQUE_PROMPT = """Evaluate the work above against the success criteria. {limit_note}Answer with a single JSON object and nothing else:
{{"criteria": [{{"id": "c1", "met": true, "confidence": 0.0, "justification": "..."}}]}}
Include every criterion id from the plan: {criteria_ids}. confidence is a number from 0 to 1."""

REPORT_PROMPT = """Write the final report as a single JSON object and nothing else:
{{"summary": "...", "actions": [{{"step_seq": 0, "description": "..."}}], "evidence": ["..."], "uncertainties": ["..."], "next_steps": ["..."]}}
step_seq refers to the numbered steps of this task: {step_index}."""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in a model answer, tolerating ``` fences and prose around it."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    match = _JSON_OBJECT.search(cleaned)
    if not match:
        raise ValueError("no JSON object found")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def derive_outcome(criteria: list[dict]) -> str:
    met = [bool(c.get("met")) and float(c.get("confidence") or 0) >= CONFIDENCE_THRESHOLD for c in criteria]
    if met and all(met):
        return "success"
    if any(met):
        return "partial"
    return "failed"


def _validate_plan(plan: dict) -> dict:
    steps, criteria = plan.get("steps"), plan.get("success_criteria")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("success_criteria must be a non-empty list")
    ids = [str(c.get("id")) for c in criteria]
    if len(set(ids)) != len(ids) or any(i in ("", "None") for i in ids):
        raise ValueError("success_criteria ids must be unique and non-empty")
    plan.setdefault("risks", [])
    return plan


def _validate_critique(critique: dict, expected_ids: list[str]) -> dict:
    criteria = critique.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("criteria must be a list")
    got = {str(c.get("id")) for c in criteria}
    if not set(expected_ids).issubset(got):
        raise ValueError(f"missing criteria: {sorted(set(expected_ids) - got)}")
    for c in criteria:
        c["met"] = bool(c.get("met"))
        c["confidence"] = max(0.0, min(1.0, float(c.get("confidence") or 0)))
        c["justification"] = str(c.get("justification") or "")
    return critique


def _validate_report(report: dict) -> dict:
    if not isinstance(report.get("summary"), str) or not report["summary"].strip():
        raise ValueError("summary must be a non-empty string")
    for key in ("actions", "evidence", "uncertainties", "next_steps"):
        if not isinstance(report.get(key), list):
            report[key] = []
    return report


class _Run:
    def __init__(self, task_id, llm, tool, tool_defs, policy_levels, session_factory, clock):
        self.task_id, self.llm, self.tool, self.tool_defs, self.policy_levels, self.sf, self.clock = (
            task_id, llm, tool, tool_defs, policy_levels, session_factory, clock)
        self.messages: list[dict] = []
        self.tools: list[dict] = []
        self.server_map = {}
        self.levels: dict[str, int] = {}
        self.ceiling = 1
        self.limit_hit: LimitHit | None = None

    async def _task(self, session) -> AgentTask:
        return await session.get(AgentTask, self.task_id)

    async def _llm_json(self, phase: str, messages: list[dict], validate) -> tuple[dict, LlmResult, list[dict]]:
        """One JSON-returning call with a single retry that quotes the parse error."""
        attempt_messages = list(messages)
        last_error = ""
        for _ in range(2):
            result = await self.llm(self.provider, self.model, self.api_key, attempt_messages, None)
            try:
                data = validate(parse_json_object(result.text))
                return data, result, attempt_messages
            except (ValueError, TypeError) as exc:
                last_error = str(exc)
                attempt_messages = attempt_messages + [
                    {"role": "assistant", "content": result.text},
                    {"role": "user", "content": f"Invalid JSON: {last_error}. Answer again with the JSON object only."},
                ]
        raise RunFailed(phase, f"{phase} phase returned invalid JSON twice: {last_error}")

    async def _check_cancel_and_deadline(self, session):
        if await AgentTaskService.is_cancel_requested(session, self.task_id):
            raise Cancelled()
        if self.clock() > self.deadline:
            self.limit_hit = LimitHit.TIMEOUT
            return False
        return True

    async def _execute_call(self, session, task, turn_seq: int, i: int, tc: dict, *, approval=None):
        server = self.server_map.get(tc["name"])
        level = self.levels.get(tc["name"], DEFAULT_RISK_LEVEL)
        t1 = self.clock()
        payload = {"tool": tc["name"], "server": server.name if server else None, "args": tc["args"],
                   # On a resume the journal records the level the approval was granted against.
                   "risk_level": approval.risk_level if approval is not None else level}
        if server is None:
            text, ok = json.dumps({"error": f"Unknown tool: {tc['name']}"}), False
        elif approval is not None and approval.status == "rejected":
            text, ok = json.dumps({"error": f"rejected by operator: {approval.decision_reason or 'no reason given'}"}), False
        elif approval is None and level > self.ceiling:
            created = await ApprovalService.request(session, task, step_seq=turn_seq, call_index=i, tool_name=tc["name"],
                                                     server_name=server.name, args=tc["args"], risk_level=level)
            raise Parked(created)
        else:
            args = approval.args if approval is not None else tc["args"]
            text = await self.tool(tc["name"], args, server)
            ok = not _looks_like_error(text)
            payload["args"] = args
        if approval is not None:
            payload["approval_id"] = str(approval.id)
        await AgentTaskService.record_step(session, task, "tool_call", {**payload, "result": text, "ok": ok},
                                           duration_ms=int((self.clock() - t1) * 1000))
        if approval is not None:
            consumed = await ApprovalService.mark_consumed(session, approval)
            if not consumed:
                log.warning("approval_already_consumed", approval_id=str(approval.id), task_id=str(task.id))
        self.messages.append({"role": "tool", "tool_call_id": f"call_{turn_seq}_{i}", "content": text})

    async def run(self):
        async with self.sf() as session:
            task = await self._task(session)
            agent = await session.get(Agent, task.agent_id)
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            if not config or not config.api_key:
                raise RunFailed("claim", "LLM not configured. Set API key in Config.")
            self.provider, self.model, self.api_key = config.llm_provider, config.llm_model, decrypt_value(config.api_key)
            servers = [s for s in agent.mcp_servers if s.enabled]
            self.tools, self.server_map = await self.tool_defs(servers)
            self.levels = await self.policy_levels(session, self.server_map)
            self.ceiling = agent.max_auto_risk
            self.started = self.clock()
            self.deadline = self.started + task.timeout_seconds

            decided = await ApprovalService.decided_unconsumed(session, task.id)
            if decided is not None:
                await self._resume(session, task, decided)
                return
            if task.step_count > 0:
                raise RunFailed("resume", "task has steps but no decided approval to resume from")

            self.messages = [{"role": "system", "content": SYSTEM_PROMPT.format(objective=task.objective, instructions=task.instructions or "(none)")}]

            # Phase 1: plan
            plan_messages = self.messages + [{"role": "user", "content": PLAN_PROMPT.format(tool_names=", ".join(sorted(self.server_map)) or "(none)")}]
            plan, result, used = await self._llm_json("plan", plan_messages, _validate_plan)
            await AgentTaskService.record_step(session, task, "plan", plan, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                               duration_ms=int((self.clock() - self.started) * 1000))
            await AgentTaskService.set_phase_output(session, task, plan=plan)

            # Phase 2: tool loop
            self.messages.append({"role": "user", "content": EXECUTE_PROMPT + "\nPlan:\n" + json.dumps(plan)})
            await self._loop(session, task, rounds=0)
            # Phases 3-4 run even after a limit, within a fixed grace.
            await self._finalize(session, task, plan)

    async def _loop(self, session, task, *, rounds: int):
        """The tool loop, from the given number of rounds already used."""
        while True:
            if rounds >= task.max_steps:
                self.limit_hit = LimitHit.MAX_STEPS
                break
            await AgentTaskService.heartbeat(session, task.id)
            if not await self._check_cancel_and_deadline(session):
                break
            rounds += 1
            t0 = self.clock()
            prompt_snapshot = json.loads(json.dumps(self.messages))
            result = await self.llm(self.provider, self.model, self.api_key, self.messages, self.tools)
            await AgentTaskService.record_step(session, task, "turn", {"text": result.text or None, "tool_calls": result.tool_calls},
                                               prompt=prompt_snapshot, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                               duration_ms=int((self.clock() - t0) * 1000))
            if not result.tool_calls:
                if result.text:
                    self.messages.append({"role": "assistant", "content": result.text})
                break
            turn_seq = task.step_count  # seq of the turn step just written; ids must match between the two messages
            self.messages.append({"role": "assistant", "content": result.text or None, "tool_calls": [
                {"id": f"call_{turn_seq}_{i}", "type": "function",
                 "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                for i, tc in enumerate(result.tool_calls)]})
            for i, tc in enumerate(result.tool_calls):
                await self._execute_call(session, task, turn_seq, i, tc)

    async def _resume(self, session, task, approval):
        """Continue after an operator decision: rebuild the history from the journal, no LLM call."""
        steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
        self.messages, turn_seq, rounds, tool_calls = _rebuild_history(steps)
        plan = task.plan
        if plan is None or turn_seq is None or approval.call_index >= len(tool_calls):
            raise RunFailed("resume", "journal has no plan or no turn to resume from")
        await AgentTaskService.heartbeat(session, task.id)
        # Apply the decision to its call, then re-gate the rest of that turn.
        await self._execute_call(session, task, turn_seq, approval.call_index, tool_calls[approval.call_index], approval=approval)
        for i in range(approval.call_index + 1, len(tool_calls)):
            await self._execute_call(session, task, turn_seq, i, tool_calls[i])
        await self._loop(session, task, rounds=rounds)
        await self._finalize(session, task, plan)

    async def _finalize(self, session, task, plan):
        grace_deadline = self.deadline + settings.AGENT_TASK_FINAL_GRACE_SECONDS
        if await AgentTaskService.is_cancel_requested(session, self.task_id):
            raise Cancelled()
        limit_note = f"The execution stopped because the limit '{self.limit_hit.value}' was reached. " if self.limit_hit else ""
        ids = [str(c["id"]) for c in plan["success_criteria"]]
        critique_messages = self.messages + [{"role": "user", "content": CRITIQUE_PROMPT.format(limit_note=limit_note, criteria_ids=", ".join(ids))}]
        remaining = grace_deadline - self.clock()
        if remaining <= 0:
            raise RunFailed("critique", "final phases exceeded the grace period")
        try:
            critique, result, used = await asyncio.wait_for(
                self._llm_json("critique", critique_messages, lambda c: _validate_critique(c, ids)),
                timeout=remaining)
        except asyncio.TimeoutError:
            raise RunFailed("critique", "final phases exceeded the grace period")
        # Only criteria the plan declared count: an invented "met" one would
        # otherwise inflate the outcome the code derives.
        declared = set(ids)
        critique["criteria"] = [c for c in critique["criteria"] if str(c.get("id")) in declared]
        critique["limit_hit"] = self.limit_hit.value if self.limit_hit else None
        await AgentTaskService.record_step(session, task, "critique", critique, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        await AgentTaskService.set_phase_output(session, task, critique=critique)
        # A cancel asked for during the critique call must still be honoured;
        # the check before the critique cannot see it.
        if await AgentTaskService.is_cancel_requested(session, self.task_id):
            raise Cancelled()

        await session.refresh(task, ["steps"])
        step_index = "; ".join(f"{s.seq}: {s.kind}" + (f" {s.payload.get('tool')}" if s.kind == "tool_call" else "") for s in task.steps)
        report_messages = self.messages + [{"role": "user", "content": REPORT_PROMPT.format(step_index=step_index or "(none)")}]
        remaining = grace_deadline - self.clock()
        if remaining <= 0:
            raise RunFailed("report", "final phases exceeded the grace period")
        try:
            report, result, used = await asyncio.wait_for(
                self._llm_json("report", report_messages, _validate_report),
                timeout=remaining)
        except asyncio.TimeoutError:
            raise RunFailed("report", "final phases exceeded the grace period")
        await AgentTaskService.record_step(session, task, "report", report, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        await AgentTaskService.set_phase_output(session, task, report=report)
        await AgentTaskService.finish(session, task, "completed", outcome=derive_outcome(critique["criteria"]))


def _rebuild_history(steps) -> tuple[list[dict], int | None, int, list[dict]]:
    """Messages as the model last saw them, the seq of the last turn, the number of turns so far, and that turn's tool calls."""
    turns = [s for s in steps if s.kind == "turn"]
    if not turns:
        return [], None, 0, []
    last = turns[-1]
    messages = json.loads(json.dumps(last.prompt or []))
    tool_calls = list(last.payload.get("tool_calls") or [])
    messages.append({"role": "assistant", "content": last.payload.get("text"), "tool_calls": [
        {"id": f"call_{last.seq}_{i}", "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
        for i, tc in enumerate(tool_calls)]})
    # Tool results recorded after that turn, in execution order: calls run
    # in index order and the gated one is always the first not yet recorded,
    # so the i-th recorded result belongs to call i.
    recorded = [s for s in steps if s.kind == "tool_call" and s.seq > last.seq]
    for i, s in enumerate(recorded):
        messages.append({"role": "tool", "tool_call_id": f"call_{last.seq}_{i}", "content": s.payload.get("result", "")})
    return messages, last.seq, len(turns), tool_calls


def _looks_like_error(text: str) -> bool:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and set(data.keys()) == {"error"}


async def run_task(task_id: uuid.UUID, *, llm=call_llm, tool=call_mcp_tool, tool_defs=build_tool_defs,
                   policy_levels=ToolPolicyService.levels_for, notify=ApprovalNotifier.notify,
                   session_factory=async_session, clock=time.monotonic) -> None:
    run = _Run(task_id, llm, tool, tool_defs, policy_levels, session_factory, clock)
    try:
        await run.run()
    except Parked as parked:
        if notify is not None:
            try:
                async with session_factory() as session:
                    await notify(session, parked.approval)
            except Exception as exc:  # noqa: BLE001 - notification never decides the task's fate
                log.warning("approval_notify_failed", approval_id=str(parked.approval.id), error=str(exc))
        return
    except ApprovalConflict:
        # The task went final (e.g. cancelled) right as we tried to park it;
        # ApprovalService already expired the approval. Nothing left to do.
        return
    except Cancelled:
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None:
                return
            if task.status in OPEN_STATUSES:
                await AgentTaskService.finish(session, task, "cancelled")
    except RunFailed as exc:
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None:
                return
            if task.status in OPEN_STATUSES:
                await AgentTaskService.record_step(session, task, "error", {"message": exc.message, "phase": exc.phase})
                await AgentTaskService.finish(session, task, "failed", error=f"{exc.phase}: {exc.message}")
    except Exception as exc:  # noqa: BLE001 - the worker must never die on one task
        log.exception("agent_task_crashed", task_id=str(task_id))
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task is None:
                return
            if task.status in OPEN_STATUSES:
                await AgentTaskService.record_step(session, task, "error", {"message": str(exc), "phase": "loop"})
                await AgentTaskService.finish(session, task, "failed", error=f"loop: {exc}")

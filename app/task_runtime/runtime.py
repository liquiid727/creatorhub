"""Database-backed task execution boundary for platform adapters.

This is intentionally independent from the legacy monitor engine. New adapter
tasks use this runtime first; existing monitor tasks can migrate one task type
at a time without changing platform adapters.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import select

from ..db import get_session
from ..models import (
    RuntimeTaskRecord,
    WriteApprovalRecord,
    WriteIdempotencyRecord,
)
from ..security import AuditLogger
from ..security import redact_text


class TaskRuntimeError(RuntimeError):
    pass


TaskHandler = Callable[[RuntimeTaskRecord, dict[str, Any]], Awaitable[dict[str, Any]]]


def _now() -> datetime:
    return datetime.utcnow()


def _task_dict(task: RuntimeTaskRecord) -> dict[str, Any]:
    try:
        payload = json.loads(task.payload_json or "{}")
    except Exception:
        payload = {}
    try:
        result = json.loads(task.result_json or "{}")
    except Exception:
        result = {}
    return {
        "id": task.id,
        "task_type": task.task_type,
        "platform": task.platform,
        "account_id": task.account_id,
        "payload": payload,
        "status": task.status,
        "idempotency_key": task.idempotency_key,
        "approval_ref": task.approval_ref,
        "requires_approval": task.requires_approval,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "result": result,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


class TaskRuntime:
    def __init__(self, *, poll_seconds: float = 2.0,
                 audit: AuditLogger | None = None):
        self.poll_seconds = poll_seconds
        self.audit = audit or AuditLogger()
        self.handlers: dict[str, TaskHandler] = {}
        self._account_locks: dict[int, asyncio.Lock] = {}
        self._last_run: dict[int, datetime] = {}
        self._loop_task: asyncio.Task | None = None

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self.handlers[task_type] = handler

    def _lock_for(self, account_id: int | None) -> asyncio.Lock:
        key = int(account_id or 0)
        if key not in self._account_locks:
            self._account_locks[key] = asyncio.Lock()
        return self._account_locks[key]

    async def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_due()
            except Exception:
                # Individual tasks carry failure state; a scheduler exception
                # must not terminate the process.
                pass
            await asyncio.sleep(self.poll_seconds)

    async def enqueue(self, *, task_type: str, payload: dict[str, Any],
                      platform: str = "", account_id: int | None = None,
                      idempotency_key: str | None = None,
                      scheduled_at: datetime | None = None,
                      max_attempts: int = 3, min_gap_seconds: int = 0,
                      requires_approval: bool = False,
                      actor_id: str = "system") -> dict[str, Any]:
        if task_type not in self.handlers:
            raise TaskRuntimeError(f"TASK_HANDLER_NOT_REGISTERED:{task_type}")
        idem = (idempotency_key or str(uuid.uuid4())).strip()
        with get_session() as session:
            existing = session.exec(select(RuntimeTaskRecord).where(
                RuntimeTaskRecord.account_id == account_id,
                RuntimeTaskRecord.task_type == task_type,
                RuntimeTaskRecord.idempotency_key == idem,
            )).first()
            if existing:
                return _task_dict(existing)
            approval_ref = ""
            status = "pending"
            if requires_approval:
                approval_ref = str(uuid.uuid4())
                status = "pending_approval"
                session.add(WriteApprovalRecord(
                    approval_ref=approval_ref, task_type=task_type,
                    account_id=account_id, status="pending", actor_id=actor_id,
                ))
            task = RuntimeTaskRecord(
                task_type=task_type, platform=platform, account_id=account_id,
                payload_json=json.dumps(payload, ensure_ascii=False), status=status,
                idempotency_key=idem, approval_ref=approval_ref,
                max_attempts=max(1, max_attempts), min_gap_seconds=max(0, min_gap_seconds),
                requires_approval=requires_approval, scheduled_at=scheduled_at,
                next_run_at=scheduled_at,
            )
            session.add(task); session.commit(); session.refresh(task)
            session.add(WriteIdempotencyRecord(
                account_id=account_id, operation=task_type,
                idempotency_key=idem, task_id=task.id,
            ))
            session.commit()
            result = _task_dict(task)
        self.audit.append(action="task.enqueued", resource_type="runtime_task",
                          resource_id=str(result["id"]), result="success",
                          account_id=account_id, platform=platform,
                          approval_ref=result["approval_ref"], idempotency_key=idem,
                          metadata={"task_type": task_type})
        return result

    async def approve(self, task_id: int, *, actor_id: str = "operator") -> dict[str, Any]:
        with get_session() as session:
            task = session.get(RuntimeTaskRecord, task_id)
            if not task:
                raise TaskRuntimeError("TASK_NOT_FOUND")
            if not task.requires_approval or not task.approval_ref:
                raise TaskRuntimeError("TASK_APPROVAL_NOT_REQUIRED")
            approval = session.exec(select(WriteApprovalRecord).where(
                WriteApprovalRecord.approval_ref == task.approval_ref)).first()
            if not approval or approval.status != "pending":
                raise TaskRuntimeError("APPROVAL_NOT_PENDING")
            approval.status = "approved"; approval.actor_id = actor_id; approval.decided_at = _now()
            task.status = "pending"; task.updated_at = _now()
            session.add(approval); session.add(task); session.commit(); session.refresh(task)
            result = _task_dict(task)
        self.audit.append(action="task.approved", resource_type="runtime_task",
                          resource_id=str(task_id), result="success", actor_id=actor_id,
                          account_id=task.account_id, platform=task.platform,
                          approval_ref=task.approval_ref)
        return result

    async def cancel(self, task_id: int, *, actor_id: str = "operator") -> dict[str, Any]:
        with get_session() as session:
            task = session.get(RuntimeTaskRecord, task_id)
            if not task:
                raise TaskRuntimeError("TASK_NOT_FOUND")
            if task.status in ("succeeded", "running"):
                raise TaskRuntimeError(f"TASK_NOT_CANCELLABLE:{task.status}")
            task.status = "canceled"; task.finished_at = _now(); task.updated_at = _now()
            session.add(task); session.commit(); result = _task_dict(task)
        self.audit.append(action="task.canceled", resource_type="runtime_task",
                          resource_id=str(task_id), result="success", actor_id=actor_id,
                          account_id=task.account_id, platform=task.platform)
        return result

    async def run_due(self) -> list[dict[str, Any]]:
        now = _now()
        with get_session() as session:
            tasks = session.exec(select(RuntimeTaskRecord).where(
                RuntimeTaskRecord.status == "pending",
                (RuntimeTaskRecord.next_run_at == None) | (RuntimeTaskRecord.next_run_at <= now),
            ).order_by(RuntimeTaskRecord.id)).all()
            ids = [task.id for task in tasks if task.id is not None]
        return [result for result in await asyncio.gather(
            *(self.run_task(task_id) for task_id in ids), return_exceptions=True
        ) if isinstance(result, dict)]

    async def run_task(self, task_id: int) -> dict[str, Any]:
        with get_session() as session:
            task = session.get(RuntimeTaskRecord, task_id)
            if not task:
                raise TaskRuntimeError("TASK_NOT_FOUND")
            account_id = task.account_id
        async with self._lock_for(account_id):
            with get_session() as session:
                task = session.get(RuntimeTaskRecord, task_id)
                if not task or task.status != "pending":
                    return _task_dict(task) if task else {"id": task_id, "status": "missing"}
                if task.requires_approval:
                    approval = session.exec(select(WriteApprovalRecord).where(
                        WriteApprovalRecord.approval_ref == task.approval_ref)).first()
                    if not approval or approval.status != "approved":
                        return _task_dict(task)
                now = _now()
                if account_id and task.min_gap_seconds:
                    last = self._last_run.get(account_id)
                    if last and (now - last).total_seconds() < task.min_gap_seconds:
                        task.next_run_at = last + timedelta(seconds=task.min_gap_seconds)
                        session.add(task); session.commit(); return _task_dict(task)
                task.status = "running"; task.attempts += 1; task.locked_at = now; task.updated_at = now
                session.add(task); session.commit()
                payload = json.loads(task.payload_json or "{}")
                task_type = task.task_type
            handler = self.handlers.get(task_type)
            if handler is None:
                return await self._fail(task_id, "TASK_HANDLER_NOT_REGISTERED", retry=False)
            try:
                result = await handler(task, payload)
            except Exception as exc:
                message = redact_text(str(exc) or exc.__class__.__name__)
                return await self._fail(task_id, message, retry=True)
            self._last_run[account_id or 0] = _now()
            with get_session() as session:
                task = session.get(RuntimeTaskRecord, task_id)
                task.status = "succeeded"; task.result_json = json.dumps(result or {}, ensure_ascii=False)
                task.error = ""; task.finished_at = _now(); task.updated_at = _now(); task.locked_at = None
                session.add(task); session.commit(); output = _task_dict(task)
            self.audit.append(action="task.succeeded", resource_type="runtime_task",
                              resource_id=str(task_id), result="success",
                              account_id=output["account_id"], platform=output["platform"],
                              metadata={"task_type": task_type, "attempts": output["attempts"]})
            return output

    async def _fail(self, task_id: int, message: str, *, retry: bool) -> dict[str, Any]:
        with get_session() as session:
            task = session.get(RuntimeTaskRecord, task_id)
            if not task:
                raise TaskRuntimeError("TASK_NOT_FOUND")
            can_retry = retry and task.attempts < task.max_attempts
            task.status = "pending" if can_retry else "failed"
            task.error = message[:500]
            task.next_run_at = _now() + timedelta(seconds=min(300, 2 ** task.attempts)) if can_retry else None
            task.finished_at = None if can_retry else _now()
            task.locked_at = None; task.updated_at = _now()
            session.add(task); session.commit(); output = _task_dict(task)
        self.audit.append(action="task.retry_scheduled" if can_retry else "task.failed",
                          resource_type="runtime_task", resource_id=str(task_id),
                          result="retry" if can_retry else "failure",
                          account_id=output["account_id"], platform=output["platform"],
                          error_code=message, metadata={"attempts": output["attempts"]})
        return output

    @staticmethod
    def serialize(task: RuntimeTaskRecord) -> dict[str, Any]:
        return _task_dict(task)

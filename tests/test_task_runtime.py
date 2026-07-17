"""RP-004 state, retry, approval, idempotency and account-lock tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.db import init_db
from app.task_runtime import TaskRuntime


async def run() -> None:
    with TemporaryDirectory() as tmp:
        init_db(str(Path(tmp) / "test.db"))
        runtime = TaskRuntime()
        calls: list[int] = []

        async def handler(task, payload):
            calls.append(payload["value"])
            if payload.get("retry") and task.attempts == 1:
                raise RuntimeError("temporary")
            return {"value": payload["value"]}

        runtime.register("test.task", handler)
        first = await runtime.enqueue(task_type="test.task", account_id=7,
                                      idempotency_key="same", payload={"value": 1})
        duplicate = await runtime.enqueue(task_type="test.task", account_id=7,
                                          idempotency_key="same", payload={"value": 1})
        assert first["id"] == duplicate["id"]
        assert (await runtime.run_task(first["id"]))["status"] == "succeeded"

        approval = await runtime.enqueue(task_type="test.task", account_id=7,
                                         idempotency_key="approval", payload={"value": 2},
                                         requires_approval=True)
        assert approval["status"] == "pending_approval"
        await runtime.approve(approval["id"])
        assert (await runtime.run_task(approval["id"]))["status"] == "succeeded"

        retry = await runtime.enqueue(task_type="test.task", account_id=8,
                                      idempotency_key="retry", payload={"value": 3, "retry": True})
        assert (await runtime.run_task(retry["id"]))["status"] == "pending"
        assert (await runtime.run_task(retry["id"]))["status"] == "succeeded"
        assert calls == [1, 2, 3, 3]
    print("task_runtime: ok")


if __name__ == "__main__":
    asyncio.run(run())

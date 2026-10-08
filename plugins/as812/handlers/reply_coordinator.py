"""Batch group messages and replace an unsent reply when a new message arrives."""

import asyncio
import logging


_log = logging.getLogger(__name__)


class GroupReplyCoordinator:
    def __init__(self, reply, debounce: float = 1.2):
        self._reply = reply
        self._debounce = debounce
        self._groups = {}
        self._closed = False

    def submit(self, group_id: str, message) -> None:
        if self._closed:
            return
        state = self._groups.get(group_id)
        if state is None:
            state = {"batch": [], "next": [], "task": None, "committed": False}
            self._groups[group_id] = state

        if state["committed"]:
            state["next"].append(message)
            return

        state["batch"].append(message)
        if state["task"] is not None:
            state["task"].cancel()
        state["task"] = asyncio.create_task(self._run(group_id, state))

    async def _run(self, group_id: str, state: dict) -> None:
        try:
            await asyncio.sleep(self._debounce)
            batch = []
            for message in tuple(state["batch"]):
                try:
                    ready = await asyncio.shield(message) if isinstance(message, asyncio.Future) else message
                except Exception as exc:
                    _log.warning("群 %s 消息预处理失败: %s", group_id, exc)
                    continue
                if ready is not None:
                    batch.append(ready)
            if not batch:
                return

            def commit() -> None:
                state["committed"] = True
                state["batch"].clear()

            await self._reply(group_id, tuple(batch), commit)
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception("群 %s 回复失败", group_id)
        finally:
            if state["task"] is asyncio.current_task():
                if state["next"] and not self._closed:
                    state["batch"] = state["next"]
                    state["next"] = []
                    state["committed"] = False
                    state["task"] = asyncio.create_task(self._run(group_id, state))
                else:
                    self._groups.pop(group_id, None)

    async def close(self) -> None:
        self._closed = True
        tasks = [state["task"] for state in self._groups.values() if state["task"]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._groups.clear()

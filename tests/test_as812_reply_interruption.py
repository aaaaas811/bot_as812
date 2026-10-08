import asyncio
import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch


MODULE_PATH = Path(__file__).parents[1] / "plugins" / "as812" / "handlers" / "reply_coordinator.py"
PLUGIN_PATH = MODULE_PATH.parents[1]


def load_coordinator():
    spec = importlib.util.spec_from_file_location("as812_reply_coordinator_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GroupReplyCoordinator


def load_handlers(cat_response=None, include_sender=False):
    package = "_as812_reply_history_test"
    modules = {}
    for name in (package, f"{package}.handlers", f"{package}.models", f"{package}.core", f"{package}.responses", "ncatbot", "ncatbot.event", "ncatbot.utils"):
        module = ModuleType(name)
        module.__path__ = []
        modules[name] = module
    qq = ModuleType("ncatbot.event.qq")
    qq.GroupMessageEvent = object
    qq.PrivateMessageEvent = object
    modules[qq.__name__] = qq
    logger = ModuleType("ncatbot.utils.logger")
    logger.get_log = lambda: logging.getLogger(__name__)
    modules[logger.__name__] = logger
    for name, symbol in (("config_manager", "ConfigManager"), ("log_manager", "LogManager")):
        module = ModuleType(f"{package}.core.{name}")
        setattr(module, symbol, object)
        modules[module.__name__] = module

    with patch.dict(sys.modules, modules):
        models_name = f"{package}.models.message_models"
        spec = importlib.util.spec_from_file_location(models_name, PLUGIN_PATH / "models" / "message_models.py")
        models = importlib.util.module_from_spec(spec)
        sys.modules[models_name] = models
        spec.loader.exec_module(models)

        handler_name = f"{package}.handlers.message_handler"
        spec = importlib.util.spec_from_file_location(handler_name, PLUGIN_PATH / "handlers" / "message_handler.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[handler_name] = module
        spec.loader.exec_module(module)

        response_handler = None
        if cat_response is not None:
            responses = ModuleType(f"{package}.responses.CatCatRes")
            responses.cat_cat_response = cat_response
            responses.get_reply_lock = lambda _group: asyncio.Lock()
            sys.modules[responses.__name__] = responses
            response_name = f"{package}.handlers.response_handler"
            spec = importlib.util.spec_from_file_location(response_name, PLUGIN_PATH / "handlers" / "response_handler.py")
            response_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(response_module)
            response_handler = response_module.ResponseHandler

        sender = None
        if include_sender:
            sender_name = f"{package}.handlers.sender"
            spec = importlib.util.spec_from_file_location(sender_name, PLUGIN_PATH / "handlers" / "sender.py")
            sender_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sender_module)
            sender = sender_module.ResponseSender
    return module.MessageHandler, models.ChatMessage, models.UserInfo, response_handler, sender


class ReplyInterruptionTests(unittest.IsolatedAsyncioTestCase):
    def test_retry_history_includes_both_senders_and_first_image(self):
        """The retried model input includes both messages, even from different users."""
        MessageHandler, ChatMessage, UserInfo, _, _ = load_handlers()
        handler = MessageHandler(
            SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812"),
            SimpleNamespace(load_group_history=lambda *_: []),
        )
        first = ChatMessage(1, UserInfo("Alice", "1"), "look", [{"type": "image", "file": "first.jpg"}], True)
        second = ChatMessage(2, UserInfo("Bob", "2"), "and this", force_reply=False)

        history = handler.build_chat_history("group", second, [first, second])

        self.assertIn("Alice: look", history[-1]["content"])
        self.assertIn("Bob: and this", history[-1]["content"])
        self.assertTrue(any("first.jpg" in item["content"] for item in history))

    async def test_passive_retry_uses_both_messages_without_recording_unsent_reply(self):
        """An older mention still triggers the batch, without logging an uncommitted answer."""
        model_inputs = []

        async def cat_response(_key, history, *_args):
            model_inputs.extend(history)
            return "combined answer"

        MessageHandler, ChatMessage, UserInfo, ResponseHandler, _ = load_handlers(cat_response)
        config = SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812", get_image_api_key=lambda: None)
        log = SimpleNamespace(load_group_history=lambda *_: [], update_personal_log_header=lambda *_: None)
        message_handler = MessageHandler(config, log)
        handler = ResponseHandler(config, log, message_handler)
        handler._load_personal_data = AsyncMock(return_value=([], "", "personal.log"))
        personal_replies = []
        handler._append_to_personal_chat_history = lambda _path, text: personal_replies.append(text)
        first = ChatMessage(1, UserInfo("Alice", "1"), "812 help", force_reply=True)
        second = ChatMessage(2, UserInfo("Bob", "2"), "more detail", force_reply=False)

        result = await handler.process_passive_response("key", second, "group", "prompt", [first, second])

        self.assertEqual(result, "combined answer")
        self.assertIn("Alice: 812 help", model_inputs[-1]["content"])
        self.assertIn("Bob: more detail", model_inputs[-1]["content"])
        self.assertEqual(personal_replies, [])
        self.assertEqual(handler._last_bot_message_time, {})

    async def test_active_retry_uses_both_messages_without_recording_unsent_reply(self):
        """An interrupted active reply also regenerates from the full batch."""
        model_inputs = []

        async def cat_response(_key, history, *_args):
            model_inputs.extend(history)
            return "combined answer"

        MessageHandler, ChatMessage, UserInfo, ResponseHandler, _ = load_handlers(cat_response)
        config = SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812", get_image_api_key=lambda: None)
        saved = []
        log = SimpleNamespace(
            load_group_history=lambda *_: [], update_personal_log_header=lambda *_: None,
            save_bot_response=lambda *_: saved.append("saved"),
        )
        handler = ResponseHandler(config, log, MessageHandler(config, log))
        handler._check_active_reply_delay = AsyncMock(return_value=True)
        handler._load_personal_data = AsyncMock(return_value=([], "", "personal.log"))
        first = ChatMessage(1, UserInfo("Alice", "1"), "first")
        second = ChatMessage(2, UserInfo("Bob", "2"), "second")

        result = await handler.process_active_response("key", "prompt", "group", [first, second])

        self.assertEqual(result, "combined answer")
        self.assertIn("Alice: first", model_inputs[-1]["content"])
        self.assertIn("Bob: second", model_inputs[-1]["content"])
        self.assertEqual(saved, [])
        self.assertEqual(handler._last_bot_message_time, {})

    async def test_sender_marks_reply_started_only_at_first_send(self):
        """The reply remains interruptible during the sender's thinking delay."""
        _, _, _, _, ResponseSender = load_handlers(include_sender=True)
        events = []

        async def post_group(_group_id, **_kwargs):
            events.append("send")
            return "message-id"

        config = SimpleNamespace(
            get=lambda key, default=None: 0.1 if key.startswith("reply_think_delay") else default,
            get_pause_multipliers=lambda: (0, 0),
            get_bt_uin=lambda: "812",
        )
        sender = ResponseSender(
            config, SimpleNamespace(save_bot_response=lambda *_: None), None,
            PLUGIN_PATH / "assests", post_group, AsyncMock(), AsyncMock(), AsyncMock(),
        )

        task = asyncio.create_task(sender.send_group_response(123, "hello", on_first_send=lambda: events.append("commit")))
        await asyncio.sleep(0.01)
        self.assertEqual(events, [])
        await asyncio.wait_for(task, 1)
        self.assertEqual(events, ["commit", "send"])

    async def test_only_sent_reply_updates_personal_log_and_active_delay(self):
        """The response timestamp and active timer move only after the sender starts."""
        async def cat_response(*_args):
            return "unused"

        MessageHandler, ChatMessage, UserInfo, ResponseHandler, _ = load_handlers(cat_response)
        config = SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812")
        log = SimpleNamespace(load_group_history=lambda *_: [])
        handler = ResponseHandler(config, log, MessageHandler(config, log))
        handler._load_personal_data = AsyncMock(return_value=([], "", "personal.log"))
        saved = []
        handler._append_to_personal_chat_history = lambda path, text: saved.append((path, text))
        handler._update_active_reply_delay = lambda: saved.append("delay updated")
        message = ChatMessage(1, UserInfo("Alice", "1"), "hello")

        await handler.record_sent_response("group", message, "answer", active=True)

        self.assertEqual(saved, [("personal.log", "812：answer"), "delay updated"])
        self.assertGreater(handler._last_bot_message_time["group"], 0)

    async def test_retry_waits_for_shared_generation_lock(self):
        """A replacement waits for the cancelled generation to release its lock."""
        async def cat_response(*_args):
            return "answer"

        MessageHandler, ChatMessage, UserInfo, ResponseHandler, _ = load_handlers(cat_response)
        config = SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812", get_image_api_key=lambda: None)
        log = SimpleNamespace(load_group_history=lambda *_: [], update_personal_log_header=lambda *_: None)
        handler = ResponseHandler(config, log, MessageHandler(config, log))
        handler._load_personal_data = AsyncMock(return_value=([], "", "personal.log"))
        lock = asyncio.Lock()
        handler._get_reply_lock = lambda _group: lock
        message = ChatMessage(1, UserInfo("Alice", "1"), "812 help", force_reply=True)

        await lock.acquire()
        task = asyncio.create_task(handler.process_passive_response("key", message, "group", "prompt", [message]))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        lock.release()
        self.assertEqual(await asyncio.wait_for(task, 1), "answer")

    async def test_active_retry_waits_for_previous_active_attempt(self):
        """A replacement active reply waits instead of dropping its batch."""
        async def cat_response(*_args):
            return "answer"

        MessageHandler, ChatMessage, UserInfo, ResponseHandler, _ = load_handlers(cat_response)
        config = SimpleNamespace(get=lambda *_: 50, get_bt_uin=lambda: "812", get_image_api_key=lambda: None)
        log = SimpleNamespace(load_group_history=lambda *_: [], update_personal_log_header=lambda *_: None)
        handler = ResponseHandler(config, log, MessageHandler(config, log))
        handler._check_active_reply_delay = AsyncMock(return_value=True)
        handler._load_personal_data = AsyncMock(return_value=([], "", "personal.log"))
        lock = asyncio.Lock()
        handler._active_reply_locks["group"] = lock
        message = ChatMessage(1, UserInfo("Alice", "1"), "hello")

        await lock.acquire()
        task = asyncio.create_task(handler.process_active_response("key", "prompt", "group", [message]))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        lock.release()
        self.assertEqual(await asyncio.wait_for(task, 1), "answer")

    async def test_new_message_cancels_generation_and_retries_with_both(self):
        """A second message before sending replaces the old generation with both inputs."""
        first_started = asyncio.Event()
        first_cancelled = asyncio.Event()
        sent = []

        async def reply(_group_id, messages, commit):
            if len(messages) == 1:
                first_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    first_cancelled.set()
                    raise
            else:
                commit()
                sent.append(tuple(messages))

        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", "first")
        await asyncio.wait_for(first_started.wait(), 1)
        coordinator.submit("group", "second")
        await asyncio.wait_for(first_cancelled.wait(), 1)
        await asyncio.wait_for(self._until(lambda: bool(sent)), 1)
        self.assertEqual(sent, [("first", "second")])

    async def test_new_message_during_pre_send_wait_also_retries(self):
        """A generated reply remains interruptible until the first send starts."""
        waiting_to_send = asyncio.Event()
        sent = []

        async def reply(_group_id, messages, commit):
            if len(messages) == 1:
                waiting_to_send.set()
                await asyncio.Event().wait()
            commit()
            sent.append(tuple(messages))

        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", "first")
        await asyncio.wait_for(waiting_to_send.wait(), 1)
        coordinator.submit("group", "second")
        await asyncio.wait_for(self._until(lambda: bool(sent)), 1)
        self.assertEqual(sent, [("first", "second")])

    async def test_message_after_send_begins_waits_for_next_round(self):
        """A message arriving after the first send does not cancel that reply."""
        sending = asyncio.Event()
        finish_send = asyncio.Event()
        sent = []

        async def reply(_group_id, messages, commit):
            commit()
            sent.append(tuple(messages))
            if messages == ("first",):
                sending.set()
                await finish_send.wait()

        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", "first")
        await asyncio.wait_for(sending.wait(), 1)
        coordinator.submit("group", "second")
        self.assertEqual(sent, [("first",)])
        finish_send.set()
        await asyncio.wait_for(self._until(lambda: len(sent) == 2), 1)
        self.assertEqual(sent, [("first",), ("second",)])

    async def test_unload_cancels_queued_reply(self):
        """Closing the plugin cannot start another batch while cancelling a send."""
        sending = asyncio.Event()
        attempts = []

        async def reply(_group_id, messages, commit):
            commit()
            attempts.append(tuple(messages))
            sending.set()
            await asyncio.Event().wait()

        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", "first")
        await asyncio.wait_for(sending.wait(), 1)
        coordinator.submit("group", "second")
        await coordinator.close()
        await asyncio.sleep(0.03)
        self.assertEqual(attempts, [("first",)])

    async def test_message_interrupts_before_its_preprocessing_finishes(self):
        """A newly received message cancels generation before its content is ready."""
        started = asyncio.Event()
        cancelled = asyncio.Event()
        sent = []

        async def reply(_group_id, messages, commit):
            if len(messages) == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            commit()
            sent.append(tuple(messages))

        loop = asyncio.get_running_loop()
        first = loop.create_future()
        first.set_result("first")
        second = loop.create_future()
        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", first)
        await asyncio.wait_for(started.wait(), 1)
        coordinator.submit("group", second)
        await asyncio.wait_for(cancelled.wait(), 1)
        self.assertFalse(second.done())
        second.set_result("second")
        await asyncio.wait_for(self._until(lambda: bool(sent)), 1)
        self.assertEqual(sent, [("first", "second")])

    async def test_failed_preprocessing_keeps_other_received_messages(self):
        """One failed input does not discard a valid message from the same batch."""
        sent = []

        async def reply(_group_id, messages, commit):
            commit()
            sent.append(tuple(messages))

        loop = asyncio.get_running_loop()
        valid = loop.create_future()
        valid.set_result("first")
        failed = loop.create_future()
        failed.set_exception(RuntimeError("parse failed"))
        coordinator = load_coordinator()(reply, debounce=0.01)
        coordinator.submit("group", valid)
        coordinator.submit("group", failed)
        await asyncio.wait_for(self._until(lambda: bool(sent)), 1)
        self.assertEqual(sent, [("first",)])

    @staticmethod
    async def _until(predicate):
        while not predicate():
            await asyncio.sleep(0.001)


if __name__ == "__main__":
    unittest.main()

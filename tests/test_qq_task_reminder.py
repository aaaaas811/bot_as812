"""Offline behavioral checks for personal QQ ingestion and deadline reminders."""
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import AsyncMock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "plugins/qq_task_reminder/core.py"


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CORE.exists(), "Personal QQ reminder core is not implemented")
        spec = importlib.util.spec_from_file_location("reminder_core", CORE)
        self.core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.core)
        (ROOT / "data").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="qq-reminder-test-", dir=ROOT / "data")
        self.addCleanup(self.temp.cleanup)
        self.store = self.core.Store(Path(self.temp.name) / "tasks.sqlite3")
        self.addCleanup(self.store.close)
        self.now = 1792749600  # 2026-10-23 18:00 Asia/Shanghai

    def event(self, **changes):
        event = dict(post_type="message", message_type="group", self_id=123,
                     group_id=456, message_id=10, user_id=789, time=self.now,
                     message=[{"type": "text", "data": {"text": "明天18:00前提交实验报告"}}])
        event.update(changes)
        return event

    def ingest(self, **changes):
        return self.store.ingest(self.event(**changes), "123", {"456"})

    def extract(self, **changes):
        self.ingest()
        item = dict(title="提交实验报告", source_id="10", quote="明天18:00前提交实验报告",
                    deadline_text="明天18:00", due_at="2026-10-24T18:00:00+08:00",
                    uncertain=False)
        item.update(changes)
        self.store.apply("456", self.store.pending("456"), json.dumps({"tasks": [item]}))
        return self.store.tasks()[0]

    def test_other_account_group_and_private_messages_are_not_stored(self):
        for changes in ({"self_id": 999}, {"group_id": 999}, {"message_type": "private"}):
            self.assertFalse(self.ingest(**changes))
        self.assertEqual(self.store.pending("456"), [])

    def test_duplicate_delivery_is_persistently_deduplicated(self):
        self.assertTrue(self.ingest())
        self.assertFalse(self.ingest())
        other = self.core.Store(Path(self.temp.name) / "tasks.sqlite3")
        try:
            self.assertFalse(other.ingest(self.event(), "123", {"456"}))
            self.assertEqual(len(other.pending("456")), 1)
        finally:
            other.close()

    def test_non_text_segments_do_not_become_task_instructions(self):
        self.assertFalse(self.ingest(message=[{"type": "image", "data": {"url": "secret"}}]))

    def test_deadline_is_resolved_from_source_and_extraction_marks_batch_processed(self):
        task = self.extract()
        self.assertEqual(task["due_at"], self.now + 86400)
        self.assertEqual(self.store.pending("456"), [])

    def test_uncertain_or_unquoted_deadline_cannot_schedule_mail(self):
        for changes in ({"uncertain": True}, {"deadline_text": "下周三"},
                        {"due_at": "2026-10-24"}, {"due_at": None}):
            with self.subTest(changes=changes):
                self.store.db.execute("DELETE FROM tasks")
                self.store.db.execute("DELETE FROM messages")
                task = self.extract(**changes)
                self.assertIsNone(task["due_at"])
                self.assertEqual(self.core.reminder_stage(task["due_at"], self.now, [86400, 3600, 0]), None)

    def test_hallucinated_source_rejects_batch_without_losing_messages(self):
        self.ingest()
        with self.assertRaises(ValueError):
            self.store.apply("456", self.store.pending("456"), json.dumps({"tasks": [
                {"title": "虚构任务", "source_id": "999", "quote": "不存在"}]}))
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(len(self.store.pending("456")), 1)

    def test_invalid_model_reply_does_not_consume_messages(self):
        self.ingest()
        with self.assertRaises(ValueError):
            self.store.apply("456", self.store.pending("456"), '{"tasks": "wrong"}')
        self.assertEqual(len(self.store.pending("456")), 1)

    def test_nearest_missed_reminder_only_is_selected(self):
        self.assertEqual(self.core.reminder_stage(self.now + 1800, self.now, [86400, 3600, 0]), 3600)
        self.assertEqual(self.core.reminder_stage(self.now - 10, self.now, [86400, 3600, 0]), 0)
        self.assertIsNone(self.core.reminder_stage(self.now + 90000, self.now, [86400, 3600, 0]))

    def test_sent_key_survives_restart(self):
        self.assertFalse(self.store.was_sent("test"))
        self.store.mark_sent("test")
        other = self.core.Store(Path(self.temp.name) / "tasks.sqlite3")
        try:
            self.assertTrue(other.was_sent("test"))
        finally:
            other.close()

    def test_deadline_update_preserves_task_identity(self):
        old = self.extract()
        self.ingest(message_id=11, message=[{"type": "text", "data": {"text": "报告改为25日18:00交"}}])
        self.store.apply("456", self.store.pending("456"), json.dumps({"tasks": [dict(
            task_id=old["id"], title="提交实验报告", source_id="11", quote="报告改为25日18:00交",
            deadline_text="25日18:00", due_at="2026-10-25T18:00:00+08:00", uncertain=False)]}))
        tasks = self.store.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], old["id"])
        self.assertEqual(tasks[0]["due_at"], self.now + 172800)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertTrue((CORE.parent / "service.py").exists(), "Reminder service is not implemented")
        from plugins.qq_task_reminder.core import Store
        from plugins.qq_task_reminder.service import Service, make_app
        from aiohttp.test_utils import TestClient, TestServer

        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.service = Service({"account": "123", "groups": ["456"], "daily_time": "21:00",
                                "reminder_hours": [24, 1, 0]}, self.store)
        self.service.send_mail = AsyncMock()
        self.client = TestClient(TestServer(make_app(self.service, "test-token")))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_receiver_rejects_missing_token(self):
        response = await self.client.post("/events", json={})
        self.assertEqual(response.status, 401)

    async def test_receiver_acknowledges_only_after_persisting_event(self):
        response = await self.client.post("/events", headers={"Authorization": "Bearer test-token"}, json=dict(
                                post_type="message", message_type="group", self_id=123, group_id=456,
                                message_id=1, time=1792749600,
                                message=[{"type": "text", "data": {"text": "提交作业"}}]))
        self.assertEqual(response.status, 200)
        self.assertEqual(self.store.pending("456")[0]["text"], "提交作业")

    def task(self):
        self.store.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
                              ("t1", "456", "报告", "1", "明天交报告", 1792836000, 1792749600))
        self.store.db.commit()

    async def test_failed_mail_is_retried_without_marking_it_delivered(self):
        self.task()
        self.service.send_mail.side_effect = OSError("SMTP unavailable")
        await self.service.notify(1792834200)  # 30 minutes before deadline
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM sent").fetchone()[0], 0)
        self.service.send_mail.side_effect = None
        await self.service.notify(1792834200)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM sent").fetchone()[0], 1)
        self.service.send_mail.reset_mock()
        await self.service.notify(1792834201)
        self.assertFalse(self.service.send_mail.called)

    async def test_daily_digest_once_per_beijing_date_even_after_restart(self):
        await self.service.notify(1792760400)  # 2026-10-23 21:00 Beijing
        self.assertTrue(self.store.was_sent("daily:2026-10-23"))
        self.service.send_mail.reset_mock()
        await self.service.notify(1792760401)
        self.assertFalse(self.service.send_mail.called)

    async def test_ai_failure_preserves_pending_messages(self):
        self.store.ingest(dict(post_type="message", message_type="group", self_id=123, group_id=456,
                               message_id=1, time=1792749600,
                               message=[{"type": "text", "data": {"text": "提交作业"}}]), "123", {"456"})
        self.service.ask_model = AsyncMock(side_effect=OSError("AI unavailable"))
        await self.service.extract()
        self.assertEqual(self.store.pending_count(), 1)

    async def test_receiver_rejects_another_account_even_with_valid_token(self):
        response = await self.client.post("/events", headers={"Authorization": "Bearer test-token"},
                                          json={"post_type": "meta_event", "self_id": 999})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.service.last_seen, 0)

    async def test_model_http_response_produces_persisted_task(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        async def model(request):
            payload = await request.json()
            inputs = json.loads(payload["messages"][1]["content"])
            self.assertEqual(inputs["messages"][0]["sent_at"], "2026-10-23 18:00")
            return web.json_response({"choices": [{"message": {"content": json.dumps({"tasks": [{
                "title": "提交报告", "source_id": "1", "quote": "明天18:00交报告", "deadline_text": "明天18:00",
                "due_at": "2026-10-24T18:00:00+08:00", "uncertain": False}]})}}]})

        app = web.Application()
        app.router.add_post("/chat/completions", model)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        self.service.config["ai"] = {"base_url": str(server.make_url("/")), "model": "test",
                                     "api_key_env": "UNUSED_QQ_TASK_TEST_KEY"}
        self.store.ingest(dict(post_type="message", message_type="group", self_id=123, group_id=456,
                               message_id=1, time=1792749600, message=[{"type": "text", "data": {
                                   "text": "明天18:00交报告"}}]), "123", {"456"})
        await self.service.extract()
        self.assertEqual(self.store.tasks()[0]["due_at"], 1792836000)
        self.assertEqual(self.store.pending_count(), 0)

    async def test_plugin_disabled_by_default_and_manifest_loads(self):
        import sdk_compat  # noqa: F401
        from ncatbot.plugin.manifest import PluginManifest
        from ncatbot.plugin.loader.importer import ModuleImporter
        from unittest.mock import patch

        importer = ModuleImporter()
        importer.add_plugin_root(str(ROOT / "plugins"))
        manifest = PluginManifest.from_toml(CORE.parent / "manifest.toml")
        module = importer.load_module(manifest)
        cls = importer.find_plugin_class(module, manifest.entry_class)
        plugin = cls()
        with patch.object(module, "PLUGIN_DIR", ROOT / "data" / "nonexistent-reminder-config"):
            await plugin.on_load()
            self.assertEqual(plugin._jobs, [])
            self.assertIsNone(plugin._runner)
            await plugin.on_close()


if __name__ == "__main__":
    unittest.main()

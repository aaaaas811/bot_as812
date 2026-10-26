"""SEU lecture protocol, public status, and QQ forwarding checks (offline)."""
import importlib
import json
import logging
from contextlib import chdir
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone(timedelta(hours=8)))


def lecture(**changes):
    row = dict(WID="one", JZMC="人工智能讲座", JZSJ="2026-10-27 14:00:00",
               HDJSSJ="2026-10-27 16:00:00", JZDD="九龙湖校区", ZJR="张老师",
               JZXL_DISPLAY="科学素养", ZBF="研究生院", HDZRS="100", YYRS="90",
               YYKSSJ="2026-10-25 12:00:00", YYJSSJ="2026-10-27 12:00:00",
               XTDQSJ="2026-10-26 12:00:00", FBZT="1", YY_WID="", SFDK="0", SFWY="0")
    row.update(changes)
    return row


class LectureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertTrue((ROOT / "plugins/seu_lectures/client.py").exists(),
                        "SEU lecture plugin is not implemented")
        self.client_module = importlib.import_module("plugins.seu_lectures.client")
        self.formatter = importlib.import_module("plugins.seu_lectures.formatter")

    def test_public_booking_status_does_not_disclose_shared_account_reservations(self):
        cases = [({}, "可预约"), ({"YYRS": 100}, "已满"),
                 ({"YYKSSJ": "2026-10-27"}, "未开放"),
                 ({"YYJSSJ": "2026-10-26 11:59"}, "预约已截止"),
                 ({"YY_WID": "private", "SFDK": "1", "SFWY": "1"}, "可预约"),
                 ({"YYKSSJ": None, "YYJSSJ": "bad"}, "状态未知")]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.formatter.booking_status(lecture(**changes), NOW), expected)

    def test_current_lectures_use_server_clock_filter_and_sort(self):
        rows = [lecture(WID="later", JZMC="后天", JZSJ="2026-10-28 14:00:00",
                        HDJSSJ="2026-10-28 16:00:00"), lecture(),
                lecture(WID="old", JZMC="往期", HDJSSJ="2026-10-26 12:00:00"),
                lecture(WID="cancel", JZMC="取消", FBZT="-1")]
        texts = self.formatter.format_lectures(rows, now=NOW + timedelta(days=50))
        self.assertEqual(len(texts), 3)
        self.assertIn("人工智能讲座", texts[1])
        self.assertIn("后天", texts[2])
        self.assertIn("剩余 10", texts[1])
        self.assertIn("九龙湖校区", texts[1])
        self.assertIn("张老师", texts[1])
        self.assertNotIn("往期", "".join(texts))

    def test_unknown_capacity_is_not_zero_seats_and_empty_results_are_explicit(self):
        text = "".join(self.formatter.format_lectures([lecture(HDZRS=None, YYRS=None)], now=NOW))
        self.assertIn("名额未知", text)
        self.assertIn("暂无", "".join(self.formatter.format_lectures([], now=NOW)))

    async def make_client(self):
        client = self.client_module.LectureClient("student", "secret", network="campus")
        self.addAsyncCleanup(client.close)
        return client

    async def test_pagination_deduplication_and_cache(self):
        client = await self.make_client()
        client.login = AsyncMock()
        client._request = AsyncMock(side_effect=[
            (200, {}, json.dumps({"datas": [lecture()], "total": 2})),
            (200, {}, json.dumps({"datas": [lecture(), lecture(WID="two")], "total": 2})),
        ])
        rows = await client.fetch()
        self.assertEqual([r["WID"] for r in rows], ["one", "two"])
        self.assertEqual(await client.fetch(), rows)
        self.assertEqual(client._request.await_count, 2)
        self.assertEqual(client._request.call_args.kwargs["params"]["pageIndex"], 2)

    async def test_expired_session_relogs_once_but_network_errors_do_not(self):
        client = await self.make_client()
        client.login = AsyncMock()
        client._request = AsyncMock(side_effect=[
            (302, {"Location": "https://auth.seu.edu.cn/dist/"}, ""),
            (200, {}, json.dumps({"datas": [lecture()], "total": 1})),
        ])
        self.assertEqual(len(await client.fetch()), 1)
        self.assertEqual(client.login.await_count, 2)

    async def test_invalid_payload_and_http_errors_are_not_empty_lists(self):
        for response in [(200, {}, '{"success":false,"msg":"secret"}'),
                         (200, {}, '{"datas":{},"total":1}'),
                         (503, {}, "maintenance"), (200, {}, "<html>login</html>")]:
            with self.subTest(response=response):
                client = await self.make_client()
                client.login = AsyncMock()
                client._request = AsyncMock(return_value=response)
                with self.assertRaises(self.client_module.LectureError) as exc:
                    await client.fetch()
                self.assertNotIn("secret", str(exc.exception))
                self.assertLessEqual(client.login.await_count, 2)
                if response[0] == 503:
                    self.assertEqual(client.login.await_count, 1)

    async def test_missing_credentials_never_attempts_network(self):
        client = self.client_module.LectureClient("", "")
        self.addAsyncCleanup(client.close)
        client._request = AsyncMock()
        with self.assertRaisesRegex(self.client_module.LectureError, "配置"):
            await client.fetch()
        client._request.assert_not_awaited()

    async def test_campus_and_offcampus_login_encrypt_password_and_exchange_cookies(self):
        import aiohttp
        import base64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from urllib.parse import quote
        from yarl import URL

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        m = self.client_module
        for offcampus in (False, True):
            with self.subTest(offcampus=offcampus):
                client = await self.make_client()
                client.network = "auto"
                client.session = aiohttp.ClientSession()
                visited = []

                async def request(method, url, **kwargs):
                    visited.append(url)
                    body, headers, status = {}, {}, 200
                    if url == "https://ehall.seu.edu.cn/":
                        if offcampus:
                            status, headers = 302, {"Location": m.PORTAL + "/controller/v1/public/verify"}
                    elif url.endswith("needCaptcha"):
                        body = {"code": 200, "needStage2Validation": False}
                    elif url.endswith("getChiperKey"):
                        body = {"publicKey": public_key}
                    elif url.endswith("casLogin"):
                        payload = kwargs["json"]
                        password = private_key.decrypt(base64.b64decode(payload["password"]), padding.PKCS1v15())
                        self.assertEqual(password, b"secret")
                        self.assertEqual(payload["username"], "student")
                        body = {"success": True}
                    elif url.endswith("verifyTgt"):
                        service = kwargs["json"]["service"]
                        body = {"redirectUrl": (m.APP_URL if service == m.APP_SERVICE else m.PORTAL + "/ticket")}
                    elif url == m.PORTAL + "/ticket":
                        status, headers = 302, {"Location": "/portal/shortcut.html?data=" + quote('{"ticket":"test-ticket"}')}
                    elif url.endswith("reportEnv"):
                        self.assertEqual(kwargs["json"]["ticket"], "test-ticket")
                        self.assertNotIn("Origin", kwargs["headers"])
                    elif url.endswith("authCheck"):
                        body = {"code": 0, "data": {"onlineInfo": {}}}
                    elif url == m.APP_URL:
                        client.session.cookie_jar.update_cookies({"GS_SESSIONID": "test-cookie"}, response_url=URL(m.APP_URL))
                    return status, headers, json.dumps(body)

                client._request = request
                await client.login()
                self.assertEqual(any(url.endswith("reportEnv") for url in visited), offcampus)
                self.assertTrue(any(c.key == "GS_SESSIONID" for c in client.session.cookie_jar))

    async def test_two_factor_requirement_stops_before_password_submission(self):
        client = await self.make_client()
        client._request = AsyncMock(side_effect=[(200, {}, ""), (200, {}, "{}"),
                                                (200, {}, '{"needStage2Validation":true}')])
        with self.assertRaisesRegex(self.client_module.LectureError, "二次验证"):
            await client.login()
        self.assertFalse(any("casLogin" in call.args[1] for call in client._request.call_args_list))


class QQIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Keep framework service state and generated config out of the live bot directory.
        temp = self.enterContext(tempfile.TemporaryDirectory(prefix="seu-test-", dir=ROOT / "data"))
        self.enterContext(chdir(temp))
        self.addCleanup(logging.shutdown)

    async def test_commands_load_and_forward_in_group_and_private(self):
        self.assertTrue((ROOT / "plugins/seu_lectures/manifest.toml").exists(),
                        "SEU lecture plugin manifest is missing")
        from ncatbot.testing import PluginTestHarness
        from ncatbot.testing.factories.qq import group_message, private_message

        async with PluginTestHarness(plugin_names=["seu_lectures"], plugins_dir=ROOT / "plugins") as h:
            self.assertIn("seu_lectures", h.loaded_plugins)
            plugin = h.get_plugin("seu_lectures")
            with patch.object(plugin.client, "fetch", AsyncMock(return_value=[lecture()])):
                for event, target, kind in [(group_message("/讲座", group_id="123"), "123", "group"),
                                            (private_message("/讲座", user_id="456"), "456", "private")]:
                    h.reset_api()
                    await h.inject(event)
                    await h.settle(0.2)
                    calls = h.mock_api.get_calls("send_forward_msg")
                    self.assertEqual(len(calls), 1, h.mock_api.calls)
                    serialized = json.dumps(calls[0].params, ensure_ascii=False)
                    self.assertEqual(calls[0].params["target_id"], target)
                    self.assertEqual(calls[0].params["message_type"], kind)
                    self.assertIn("人工智能讲座", serialized)
                    self.assertIn("可预约", serialized)
                h.reset_api()
                await h.inject(group_message("讲座是什么"))
                await h.inject(private_message("/讲座测试"))
                await h.settle(0.1)
                self.assertEqual(h.mock_api.calls, [])
            with patch.object(plugin.client, "fetch", AsyncMock(return_value=[])):
                await h.inject(private_message("/讲座"))
                await h.settle(0.1)
                self.assertIn("暂无", str(h.mock_api.get_calls("send_forward_msg")))
            h.reset_api()
            with patch.object(plugin.client, "fetch", AsyncMock(side_effect=TimeoutError("secret"))):
                await h.inject(group_message("/讲座"))
                await h.settle(0.1)
                self.assertIn("超时", str(h.mock_api.calls))
                self.assertNotIn("secret", str(h.mock_api.calls))
            h.reset_api()
            rows = [lecture(WID=str(i), JZMC=f"讲座{i:02}") for i in range(51)]
            with patch.object(plugin.client, "fetch", AsyncMock(return_value=rows)):
                await h.inject(group_message("/讲座"))
                await h.settle(0.2)
                calls = h.mock_api.get_calls("send_forward_msg")
                self.assertEqual(len(calls), 2)
                self.assertEqual(sum(len(c.params["messages"]) for c in calls), 52)
            h.reset_api()
            with patch.object(plugin.client, "fetch", AsyncMock(return_value=[lecture()])), \
                    patch.object(h.mock_api, "send_forward_msg", AsyncMock(side_effect=RuntimeError("secret"))):
                await h.inject(private_message("/讲座"))
                await h.settle(0.1)
                self.assertIn("发送失败", str(h.mock_api.calls))
                self.assertNotIn("secret", str(h.mock_api.calls))


if __name__ == "__main__":
    unittest.main()

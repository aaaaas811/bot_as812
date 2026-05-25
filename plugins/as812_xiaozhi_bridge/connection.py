"""xiaozhi-server WebSocket 连接管理"""
import asyncio
import json
import time
from typing import Optional

import websockets
from ncatbot.utils.logger import get_log

_log = get_log()


class ConnectionError(Exception):
    """xiaozhi-server 连接失败"""


class ResponseTimeout(Exception):
    """xiaozhi-server 响应超时"""


class XiaozhiConnection:
    """单个 WebSocket 会话，对应 xiaozhi-server 的一个 ConnectionHandler"""

    def __init__(self, user_id: str, config: dict):
        self._user_id = user_id
        self._config = config
        server_cfg = config["xiaozhi_server"]
        self._url = server_cfg["url"]
        self._connect_timeout = server_cfg.get("connect_timeout", 15)
        self._response_timeout = server_cfg.get("response_timeout", 120)
        self._hello_params = server_cfg.get("hello_params", {})
        self._target_device_id = server_cfg.get("target_device_id", "")

        headers = {
            "Device-ID": server_cfg.get("device_id", "qq-bot-bridge"),
            "Client-ID": server_cfg.get("client_id", "qq-bot-client"),
        }
        auth = server_cfg.get("authorization", "")
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        self._headers = headers

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self._response_future: Optional[asyncio.Future] = None
        self._text_buffer: list[str] = []
        self._expecting_response = False
        self._closed = False

    async def connect(self) -> bool:
        """建立 WebSocket 连接并完成 hello 握手"""
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self._url,
                    additional_headers=self._headers,
                ),
                timeout=self._connect_timeout,
            )
        except Exception as e:
            _log.error(f"[xiaozhi] 连接失败 user={self._user_id}: {e}")
            self._closed = True
            return False

        # 发送 hello
        await self._ws.send(json.dumps({
            "type": "hello",
            "audio_params": self._hello_params.get("audio_params", {
                "format": "opus",
                "sample_rate": 24000,
                "channels": 1,
                "frame_duration": 60,
            }),
            "features": {},
        }))

        # 等待服务器 welcome
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self._connect_timeout)
            msg = json.loads(raw)
            if msg.get("type") == "hello":
                session_id = msg.get("session_id", "")
                _log.info(f"[xiaozhi] 连接成功 user={self._user_id} session={session_id}")
            else:
                _log.warning(f"[xiaozhi] hello 响应异常: {msg}")
        except Exception as e:
            _log.error(f"[xiaozhi] hello 握手失败 user={self._user_id}: {e}")
            await self._ws.close()
            self._closed = True
            return False

        self._reader_task = asyncio.create_task(self._reader_loop())
        return True

    async def send_text(self, text: str) -> str:
        """通过 bridge 将文本注入目标 ESP32 设备，等待 TTS 响应镜像"""
        if not self._target_device_id:
            raise ConnectionError("未配置 target_device_id，无法桥接消息")

        async with self._send_lock:
            self._expecting_response = True
            self._text_buffer.clear()
            self._response_future = asyncio.get_event_loop().create_future()

            try:
                await self._ws.send(json.dumps({
                    "type": "bridge",
                    "target_device_id": self._target_device_id,
                    "text": text,
                }))
            except Exception as e:
                self._expecting_response = False
                self._closed = True
                raise ConnectionError(f"发送消息失败: {e}")

            try:
                result = await asyncio.wait_for(
                    self._response_future,
                    timeout=self._response_timeout,
                )
                return result
            except asyncio.TimeoutError:
                self._expecting_response = False
                raise ResponseTimeout("等待响应超时")

    async def _reader_loop(self):
        """后台读取 WebSocket 消息并分发处理"""
        try:
            async for message in self._ws:
                # 二进制消息（Opus 音频）直接忽略
                if isinstance(message, bytes):
                    continue

                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "bridge_response":
                    err = msg.get("error", "")
                    if self._response_future and not self._response_future.done():
                        if err:
                            self._response_future.set_exception(ConnectionError(err))
                        else:
                            self._response_future.set_result(msg.get("text", ""))
                    self._expecting_response = False
                    continue
                if msg_type != "tts":
                    continue

                if not self._expecting_response:
                    continue

                state = msg.get("state", "")
                if state == "sentence_start":
                    text = msg.get("text", "")
                    if text:
                        self._text_buffer.append(text)
                elif state == "stop":
                    if self._response_future and not self._response_future.done():
                        result = "".join(self._text_buffer)
                        self._response_future.set_result(result)
                    self._expecting_response = False
        except websockets.exceptions.ConnectionClosed as e:
            _log.warning(f"[xiaozhi] 连接关闭 user={self._user_id}: {e}")
        except Exception as e:
            _log.error(f"[xiaozhi] 读取异常 user={self._user_id}: {e}")
        finally:
            self._closed = True
            if self._response_future and not self._response_future.done():
                self._response_future.set_exception(
                    ConnectionError("xiaozhi-server 连接断开")
                )

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self):
        """关闭连接"""
        self._closed = True
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._response_future and not self._response_future.done():
            self._response_future.set_exception(
                ConnectionError("连接已关闭")
            )


class ConnectionManager:
    """管理 per-user 的 WebSocket 连接池"""

    def __init__(self, config: dict):
        self._config = config
        self._connections: dict[str, XiaozhiConnection] = {}

    async def send_message(self, user_id: str, text: str) -> str:
        """向 xiaozhi-server 发送消息并返回响应"""
        conn = await self._get_or_create_connection(user_id)

        try:
            return await conn.send_text(text)
        except (ConnectionError, ResponseTimeout):
            raise
        except Exception as e:
            _log.error(f"[xiaozhi] 发送异常 user={user_id}: {e}")
            # 重试一次（新建连接）
            await self._remove_connection(user_id)
            conn = await self._get_or_create_connection(user_id)
            return await conn.send_text(text)

    async def _get_or_create_connection(self, user_id: str) -> XiaozhiConnection:
        conn = self._connections.get(user_id)
        if conn and not conn.closed:
            return conn

        # 清理已关闭的旧连接
        if conn and conn.closed:
            await conn.close()
            del self._connections[user_id]

        conn = XiaozhiConnection(user_id, self._config)
        max_retries = self._config["xiaozhi_server"].get("max_retries", 3)
        retry_delay = self._config["xiaozhi_server"].get("retry_base_delay", 2)

        for attempt in range(max_retries):
            if await conn.connect():
                self._connections[user_id] = conn
                return conn
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))

        raise ConnectionError("无法连接到 xiaozhi-server")

    async def _remove_connection(self, user_id: str):
        conn = self._connections.pop(user_id, None)
        if conn:
            await conn.close()

    async def close_all(self):
        for user_id in list(self._connections.keys()):
            await self._remove_connection(user_id)

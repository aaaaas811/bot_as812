"""NcatBot lifecycle entry. Personal account messages stay outside Bot handlers."""
import asyncio
import logging
import os
import tomllib
from datetime import datetime
from pathlib import Path

from aiohttp import web
from ncatbot.plugin import NcatBotPlugin

from .core import Store
from .service import Service, make_app

LOG = logging.getLogger(__name__)
PLUGIN_DIR = Path(__file__).parent


class QQTaskReminder(NcatBotPlugin):
    name = "qq_task_reminder"
    version = "0.1.0"

    async def on_load(self):
        self._jobs = []
        self._runner = None
        self._store = None
        path = PLUGIN_DIR / "config.toml"
        if not path.exists():
            LOG.info("[qq_task_reminder] disabled: configure config.toml first")
            return
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        if not config.get("enabled", False):
            return
        if not str(config.get("account", "")).isdigit() or not config.get("groups"):
            raise ValueError("Configure personal account and group allowlist")
        if not all(str(group).isdigit() for group in config["groups"]):
            raise ValueError("Group IDs must be numeric")
        daily = config.get("daily_time", "21:00")
        if datetime.strptime(daily, "%H:%M").strftime("%H:%M") != daily:
            raise ValueError("daily_time must use HH:MM")
        if config.get("extract_interval_seconds", 300) < 30:
            raise ValueError("Extraction interval must be at least 30 seconds")
        if not config.get("reminder_hours") or any(hour < 0 for hour in config["reminder_hours"]):
            raise ValueError("reminder_hours must contain nonnegative offsets")
        smtp = config["smtp"]
        if smtp.get("security", "ssl") not in {"ssl", "starttls"}:
            raise ValueError("SMTP must use ssl or starttls")
        for key in ("host", "sender", "recipient", "username"):
            if not smtp.get(key):
                raise ValueError(f"Missing SMTP {key}")
        if not config["ai"].get("base_url") or not config["ai"].get("model"):
            raise ValueError("Configure AI base_url and model")
        token = os.environ[config.get("token_env", "QQ_TASK_ONEBOT_TOKEN")]
        if not os.environ.get(smtp.get("password_env", "QQ_TASK_SMTP_PASSWORD")):
            raise ValueError("SMTP password environment variable is required")
        data = PLUGIN_DIR.parents[1] / "data" / "qq_task_reminder"
        data.mkdir(parents=True, exist_ok=True)
        self._store = Store(data / "tasks.sqlite3")
        self._service = Service(config, self._store)
        try:
            self._runner = web.AppRunner(make_app(self._service, token), access_log=None)
            await self._runner.setup()
            await web.TCPSite(self._runner, config.get("listen_host", "127.0.0.1"), config.get("listen_port", 8098)).start()
            self._jobs = [asyncio.create_task(self._service.extraction_loop()),
                          asyncio.create_task(self._service.notification_loop())]
        except Exception:
            await self.on_close()
            raise
        LOG.info("[qq_task_reminder] receiver and reminder scheduler started")

    async def on_close(self):
        for job in self._jobs:
            job.cancel()
        await asyncio.gather(*self._jobs, return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._store is not None:
            self._store.close()
            self._store = None

"""Read-only SEU client. Protocol adapted from only9464/seuszjz (MIT)."""
import asyncio
import base64
import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

AUTH = "https://auth.seu.edu.cn"
PORTAL = "https://vpn.seu.edu.cn"
CAS_SERVICE = PORTAL + ":443/passport/v1/auth/cas?sfDomain=CAS-auth"
APP_SERVICE = "http://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/*default/index.do"
APP_URL = "https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/*default/index.do"
ACTIVITY_URL = "https://ehall.seu.edu.cn/gsapp/sys/jzxxtjapp/hdyy/queryActivityList.do"
PORTAL_PARAMS = {"clientType": "SDPBrowserClient", "platform": "Linux", "lang": "zh-CN"}


class LectureError(RuntimeError):
    """A safe, user-facing error without remote bodies or credentials."""


class SessionExpired(LectureError):
    pass


class LectureClient:
    def __init__(self, username, password, network="auto"):
        self.username = username
        self.password = password
        self.network = network
        self.session = None
        self._logged_in = False
        self._lock = asyncio.Lock()
        self._cached = []
        self._cached_at = None

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _request(self, method, url, **kwargs):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"},
            )
        async with self.session.request(method, url, allow_redirects=False, **kwargs) as response:
            return response.status, response.headers, await response.text()

    async def _json(self, method, url, *, activity=False, **kwargs):
        status, _, body = await self._request(method, url, **kwargs)
        if activity and (300 <= status < 400 or status in (401, 403)):
            raise SessionExpired("讲座登录状态已失效，请稍后重试。")
        if not 200 <= status < 300:
            raise LectureError("学校服务暂不可用，请稍后重试。")
        try:
            result = json.loads(body)
        except ValueError:
            if activity:
                raise SessionExpired("讲座登录状态已失效，请稍后重试。") from None
            raise LectureError("学校认证响应异常，请稍后重试。") from None
        if not isinstance(result, dict):
            raise LectureError("讲座接口数据格式异常，请稍后重试。")
        return result

    async def login(self):
        if self.network not in {"auto", "campus", "offcampus"}:
            raise LectureError("请管理员检查 SEU_NETWORK 配置。")
        if self.session is not None:
            self.session.cookie_jar.clear()
        network = self.network
        if network == "auto":
            status, headers, _ = await self._request("GET", "https://ehall.seu.edu.cn/")
            if status >= 400:
                raise LectureError("学校服务暂不可用，请稍后重试。")
            network = "offcampus" if urlparse(headers.get("Location", "")).hostname == "vpn.seu.edu.cn" else "campus"
        headers = {"Origin": AUTH, "Referer": AUTH + "/dist/"}
        await self._request("GET", AUTH + "/dist/")
        await self._json("POST", AUTH + "/auth/casback/verifyTgt", json={"service": CAS_SERVICE}, headers=headers)
        check = await self._json("GET", AUTH + "/auth/casback/needCaptcha", headers=headers)
        if check.get("needStage2Validation"):
            raise LectureError("SEU 账号需要二次验证，请管理员先在学校网页完成验证。")
        if str(check.get("code", 200)) != "200":
            raise LectureError("SEU 认证检查失败，请管理员检查账号。")
        key = await self._json("POST", AUTH + "/auth/casback/getChiperKey", json={}, headers=headers)
        try:
            raw = key["publicKey"]
            if "BEGIN" in raw:
                public_key = serialization.load_pem_public_key(raw.encode())
            else:
                public_key = serialization.load_der_public_key(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            encrypted = base64.b64encode(public_key.encrypt(self.password.encode(), padding.PKCS1v15())).decode()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise LectureError("SEU 登录加密失败，请管理员检查认证接口。") from None
        result = await self._json("POST", AUTH + "/auth/casback/casLogin", headers=headers, json={
            "service": CAS_SERVICE, "username": self.username, "password": encrypted,
            "captcha": "", "rememberMe": False, "loginType": "account", "wxBinded": False,
            "mobilePhoneNum": "", "fingerPrint": "stable_" + hashlib.md5(self.username.encode()).hexdigest(),
        })
        if result.get("needStage2Validation"):
            raise LectureError("SEU 账号需要二次验证，请管理员先在学校网页完成验证。")
        if result.get("success") is not True:
            raise LectureError("SEU 登录失败，请管理员检查账号密码或验证码要求。")
        if network == "offcampus":
            await self._portal_login()
        ticket = await self._json("POST", AUTH + "/auth/casback/verifyTgt", json={"service": APP_SERVICE})
        current = ticket.get("redirectUrl")
        for _ in range(8):
            if not current:
                break
            status, headers, _ = await self._request("GET", current)
            if self.session is not None and any(c.key == "GS_SESSIONID" for c in self.session.cookie_jar):
                return
            if not 300 <= status < 400 or not headers.get("Location"):
                break
            current = urljoin(current, headers["Location"])
        raise LectureError("SEU 应用登录失败，请管理员检查校园网/校外网络配置。")

    async def _portal_login(self):
        ticket = await self._json("POST", AUTH + "/auth/casback/verifyTgt", json={"service": CAS_SERVICE})
        redirect = ticket.get("redirectUrl")
        if not redirect:
            raise LectureError("SEU 网关票据获取失败，请稍后重试。")
        _, headers, _ = await self._request("GET", redirect)
        location = headers.get("Location", "")
        try:
            sid_ticket = json.loads(parse_qs(urlparse(location).query)["data"][0])["ticket"]
        except (KeyError, ValueError, IndexError, TypeError):
            raise LectureError("SEU 网关认证失败，请稍后重试。") from None
        referer = urljoin(PORTAL, location)
        await self._request("GET", referer)
        headers = {"x-csrf-token": str(uuid.uuid4()), "x-sdp-traceid": secrets.token_hex(4), "Referer": referer}
        device = "00" + secrets.token_hex(33)
        await self._request("POST", PORTAL + "/controller/v1/public/reportEnv", params=PORTAL_PARAMS,
                            headers=headers, json={"ticket": sid_ticket, "deviceId": device,
                            "env": {"endpoint": {"device_id": device, "device": {"type": "browser"}}}})
        check = await self._json("GET", PORTAL + "/passport/v1/auth/authCheck", params=PORTAL_PARAMS, headers=headers)
        if str(check.get("code")) != "0":
            raise LectureError("SEU 校外网关未放行，请稍后重试。")

    async def _fetch_pages(self):
        items, seen = [], set()
        for page in range(1, 51):
            data = await self._json("GET", ACTIVITY_URL, activity=True,
                                    params={"pageIndex": page, "pageSize": 50}, headers={"Referer": APP_URL})
            rows = data.get("datas")
            if data.get("success") is False or not isinstance(rows, list):
                raise LectureError("讲座接口返回异常，请稍后重试。")
            try:
                total = int(data["total"]) if data.get("total") is not None else None
            except (ValueError, TypeError):
                raise LectureError("讲座接口数据格式异常，请稍后重试。") from None
            previous = len(items)
            for row in rows:
                if not isinstance(row, dict) or not row.get("WID"):
                    raise LectureError("讲座接口数据格式异常，请稍后重试。")
                key = str(row["WID"])
                if key not in seen:
                    seen.add(key)
                    items.append(row)
            if total is not None and len(items) >= total:
                return items
            if not rows or (total is None and len(rows) < 50):
                if total is not None and len(items) < total:
                    raise LectureError("讲座列表未能完整获取，请稍后重试。")
                return items
            if len(items) == previous:
                break
        raise LectureError("讲座列表未能完整获取，请稍后重试。")

    async def fetch(self):
        if not self.username or not self.password:
            raise LectureError("讲座查询尚未配置，请管理员设置 SEU_USERNAME 和 SEU_PASSWORD 后重载插件。")
        async with self._lock:
            if self._cached_at is not None and time.monotonic() - self._cached_at < 60:
                return self._cached
            async with asyncio.timeout(60):
                for attempt in range(2):
                    if not self._logged_in:
                        await self.login()
                        self._logged_in = True
                    try:
                        rows = await self._fetch_pages()
                    except SessionExpired:
                        self._logged_in = False
                        if attempt:
                            raise
                    else:
                        self._cached, self._cached_at = rows, time.monotonic()
                        return rows

import sys
from types import ModuleType, SimpleNamespace

import pytest

from bilibili_login_compat import patch_bilibili_qr_login


def _install_fake_bilibili(monkeypatch, credential):
    login_v2 = ModuleType("bilibili_api.login_v2")
    login_v2.QrCodeLoginChannel = SimpleNamespace(WEB="web", TV="tv")

    class QrCodeLogin:
        def __init__(self, platform="web"):
            self.platform = platform

        def get_credential(self):
            return credential

    login_v2.QrCodeLogin = QrCodeLogin
    package = ModuleType("bilibili_api")
    package.login_v2 = login_v2
    monkeypatch.setitem(sys.modules, "bilibili_api", package)
    monkeypatch.setitem(sys.modules, "bilibili_api.login_v2", login_v2)
    patch_bilibili_qr_login()
    return QrCodeLogin


def test_ncatbot_web_qr_uses_tv_channel(monkeypatch):
    credential = SimpleNamespace(sessdata="session", bili_jct="csrf")
    qr_type = _install_fake_bilibili(monkeypatch, credential)
    qr = qr_type("web")
    assert qr.platform == "tv"
    assert qr.get_credential() is credential


def test_missing_session_is_rejected_before_config_save(monkeypatch):
    qr_type = _install_fake_bilibili(
        monkeypatch, SimpleNamespace(sessdata="", bili_jct="csrf")
    )
    with pytest.raises(RuntimeError, match="SESSDATA"):
        qr_type("web").get_credential()

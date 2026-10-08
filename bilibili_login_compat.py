"""Use the structured Bilibili TV QR response for NcatBot login."""

from __future__ import annotations


def patch_bilibili_qr_login() -> None:
    from bilibili_api import login_v2

    qr_type = login_v2.QrCodeLogin
    original_init = qr_type.__init__
    original_get_credential = qr_type.get_credential

    def init(self, platform=login_v2.QrCodeLoginChannel.WEB):
        if platform == login_v2.QrCodeLoginChannel.WEB:
            platform = login_v2.QrCodeLoginChannel.TV
        original_init(self, platform)

    def get_credential(self):
        credential = original_get_credential(self)
        if not credential.sessdata or not credential.bili_jct:
            raise RuntimeError(
                "Bilibili 扫码已确认，但未取得 SESSDATA 或 bili_jct；请检查扫码账号的登录状态"
            )
        return credential

    qr_type.__init__ = init
    qr_type.get_credential = get_credential


def install_bilibili_login_patch() -> None:
    """Patch after NcatBot has installed the optional Bilibili dependency."""
    from ncatbot.adapter.bilibili.adapter import BilibiliAdapter

    original_setup = BilibiliAdapter.setup

    async def setup(self):
        patch_bilibili_qr_login()
        await original_setup(self)

    BilibiliAdapter.setup = setup

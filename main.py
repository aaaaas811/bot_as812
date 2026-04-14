"""Bot bootstrap entry for NcatBot 5.x.

Root entry only starts the framework; business logic is implemented as plugins.
"""

from __future__ import annotations

import sdk_compat  # noqa: F401
from ncatbot.app import BotClient


bot = BotClient()


if __name__ == "__main__":
    bot.run()


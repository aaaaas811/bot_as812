"""NcatBot plugin entry point for the Steam status monitor."""

from .src.plugin.steam_status_monitor import SteamStatusMonitorV3


class SteamStatusMonitorPlugin(SteamStatusMonitorV3):
    """Expose the migrated implementation to NcatBot's plugin loader."""


__all__ = ["SteamStatusMonitorPlugin"]

"""Auto-update checker for NcatBot and NapCat.

Runs before bot startup to check and apply updates.
- NcatBot: checks PyPI for newer version, pip install -U if needed
- NapCat: checks GitHub releases for newer version, downloads and extracts if needed

Safe to run repeatedly; only acts when an update is actually available.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
NAPCAT_DIR = PROJECT_ROOT / "napcat"
NAPCAT_VERSION_FILE = NAPCAT_DIR / ".napcat_version"

NAPCAT_RELEASES_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases"
NAPCAT_LATEST_URL = "https://github.com/NapNeko/NapCatQQ/releases/latest"
NAPCAT_DOWNLOAD_TEMPLATE = (
    "https://github.com/NapNeko/NapCatQQ/releases/download/v{version}/NapCat.Shell.zip"
)

PYPI_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
PYPI_JSON_TEMPLATE = "https://pypi.org/pypi/{package}/json"

# ---- helpers ----


def _get_venv_python() -> str:
    """Return path to the project's .venv python, falling back to current interpreter."""
    if sys.platform.startswith("win"):
        candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = PROJECT_ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _pip_list_version(python: str, package: str) -> Optional[str]:
    """Get installed version of *package* via pip list."""
    try:
        result = subprocess.run(
            [python, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        packages = json.loads(result.stdout)
        for pkg in packages:
            if pkg["name"].lower() == package.lower():
                return pkg["version"]
    except Exception:
        pass
    return None


def _get_napcat_local_version() -> Optional[str]:
    """Read locally recorded NapCat release version."""
    if NAPCAT_VERSION_FILE.exists():
        return NAPCAT_VERSION_FILE.read_text(encoding="utf-8").strip()
    return None


def _set_napcat_local_version(version: str) -> None:
    NAPCAT_VERSION_FILE.write_text(version, encoding="utf-8")


def _detect_ncatbot_package(python: str) -> str:
    """Detect which package to update: ncatbot5 if installed, else ncatbot."""
    if _pip_list_version(python, "ncatbot5"):
        return "ncatbot5"
    return "ncatbot"


# ---- NcatBot ----


def _get_pypi_latest(package: str) -> Optional[str]:
    """Get latest version for *package* from PyPI JSON."""
    try:
        resp = requests.get(PYPI_JSON_TEMPLATE.format(package=package), timeout=15)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception:
        return None


def check_ncatbot() -> dict:
    """Detect the active ncatbot package and return current/latest versions.

    Returns dict with keys: package, installed, latest
    """
    python = _get_venv_python()
    pkg = _detect_ncatbot_package(python)
    installed = _pip_list_version(python, pkg)
    latest = _get_pypi_latest(pkg)
    return {"package": pkg, "installed": installed, "latest": latest}


def update_ncatbot(package: str) -> bool:
    """pip install -U *package*. Returns True on success.

    For ncatbot5: uses --force-reinstall to ensure all namespace-shared files
    are correctly restored after the update (ncatbot5 and ncatbot v4 share the
    ``ncatbot`` namespace directory, so a plain -U may leave stale v4 files).
    """
    python = _get_venv_python()
    print(f"[ncatbot] updating {package} via pip ...")
    extra_args = ["--force-reinstall"] if package == "ncatbot5" else []
    try:
        result = subprocess.run(
            [python, "-m", "pip", "install", package, "-U", "-i", PYPI_INDEX] + extra_args,
            capture_output=False,
            timeout=300,
        )
        ok = result.returncode == 0
        if ok:
            new_ver = _pip_list_version(python, package)
            print(f"[ncatbot] {package} updated to v{new_ver}")
        return ok
    except Exception:
        return False


# ---- NcatBot ----


def check_napcat() -> tuple[Optional[str], Optional[str]]:
    """Return (local_version, latest_version) for NapCat from GitHub releases.

    local_version is read from .napcat_version file.
    """
    local = _get_napcat_local_version()

    # If no local record but napcat dir exists, try package.json
    if local is None:
        pkg_json = NAPCAT_DIR / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                local = data.get("version")
            except Exception:
                pass

    # Fetch latest from GitHub API
    try:
        resp = requests.get(NAPCAT_RELEASES_API, timeout=15)
        resp.raise_for_status()
        releases = resp.json()
        if releases and isinstance(releases, list) and len(releases) > 0:
            latest = releases[0]["tag_name"].lstrip("v")
        else:
            latest = None
    except Exception:
        # Fallback: redirect
        try:
            r = requests.head(NAPCAT_LATEST_URL, allow_redirects=True, timeout=10)
            latest = r.url.rsplit("/", 1)[-1].lstrip("v")
        except Exception:
            latest = None

    return local, latest


def update_napcat() -> bool:
    """Download and extract latest NapCat.Shell.zip into ./napcat/. Returns True on success."""
    _, latest = check_napcat()
    if not latest:
        print("[napcat] could not determine latest version, aborting update")
        return False

    download_url = NAPCAT_DOWNLOAD_TEMPLATE.format(version=latest)
    zip_path = PROJECT_ROOT / f"napcat_v{latest}.zip"

    print(f"[napcat] downloading {download_url} ...")
    try:
        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        print(f"[napcat] download failed: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return False

    print(f"[napcat] extracting to {NAPCAT_DIR} ...")
    config_backup: dict[str, str] = {}
    config_dir = NAPCAT_DIR / "config"
    if config_dir.exists():
        for f in config_dir.iterdir():
            if f.is_file():
                config_backup[f.name] = f.read_bytes()

    try:
        import shutil

        if NAPCAT_DIR.exists():
            shutil.rmtree(NAPCAT_DIR, ignore_errors=True)
        NAPCAT_DIR.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(NAPCAT_DIR)

        # Restore backed-up config files
        if config_backup:
            config_dir.mkdir(parents=True, exist_ok=True)
            for name, data in config_backup.items():
                (config_dir / name).write_bytes(data)

        _set_napcat_local_version(latest)
        print(f"[napcat] updated to v{latest}")
    except Exception as e:
        print(f"[napcat] extraction failed: {e}")
        return False
    finally:
        if zip_path.exists():
            zip_path.unlink()

    return True


# ---- combined entry ----


def run_checks(apply_updates: bool = True) -> dict:
    """Run both checks. If *apply_updates* is True, also perform updates.

    Returns a dict with the result summary.
    """
    result: dict = {"ncatbot": {}, "napcat": {}}

    # -- ncatbot --
    print("=" * 50)
    print("[ncatbot] checking for updates ...")
    nb_info = check_ncatbot()
    nb_pkg = nb_info["package"]
    nb_installed = nb_info["installed"]
    nb_latest = nb_info["latest"]
    print(f"[ncatbot] package={nb_pkg}, installed={nb_installed}, latest={nb_latest}")

    if nb_installed and nb_latest and nb_installed != nb_latest:
        result["ncatbot"] = {
            "action": "update",
            "package": nb_pkg,
            "installed": nb_installed,
            "latest": nb_latest,
        }
        if apply_updates:
            ok = update_ncatbot(nb_pkg)
            result["ncatbot"]["success"] = ok
            if ok:
                result["ncatbot"]["new_version"] = _pip_list_version(
                    _get_venv_python(), nb_pkg
                )
    else:
        result["ncatbot"] = {
            "action": "skip",
            "package": nb_pkg,
            "installed": nb_installed,
            "latest": nb_latest,
        }

    # -- napcat --
    print("-" * 50)
    print("[napcat] checking for updates ...")
    nc_local, nc_latest = check_napcat()
    print(f"[napcat] local={nc_local}, latest={nc_latest}")

    if nc_local and nc_latest and nc_local != nc_latest:
        result["napcat"] = {
            "action": "update",
            "local": nc_local,
            "latest": nc_latest,
        }
        if apply_updates:
            ok = update_napcat()
            result["napcat"]["success"] = ok
    elif not nc_local and not NAPCAT_DIR.exists():
        # First install
        result["napcat"] = {
            "action": "install",
            "local": nc_local,
            "latest": nc_latest,
        }
        if apply_updates:
            ok = update_napcat()
            result["napcat"]["success"] = ok
    else:
        result["napcat"] = {
            "action": "skip",
            "local": nc_local,
            "latest": nc_latest,
        }

    print("=" * 50)
    return result


if __name__ == "__main__":
    run_checks(apply_updates=True)

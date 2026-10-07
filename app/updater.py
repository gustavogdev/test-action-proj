"""Self-update logic: checks GitHub Releases on the private repo and replaces
the running PyInstaller executable with a newer build when one is available.

GITHUB_TOKEN_EMBEDDED and GITHUB_REPO below are placeholders overwritten by
.github/workflows/release.yml at build time (same mechanism as app/_version.py).
"""
import os
import sys
import shutil
import subprocess
import tempfile

import requests
from packaging.version import Version

from app._version import __version__

GITHUB_TOKEN_EMBEDDED = "REPLACED_AT_BUILD_TIME"
GITHUB_REPO = "REPLACED_AT_BUILD_TIME"  # "owner/repo"

API_URL = "https://api.github.com/repos/{repo}/releases/latest"

PLATFORM_ASSET_NAMES = {
    "win32": "myapp-windows.exe",
    "darwin": "myapp-macos",
    "linux": "myapp-linux",
}


def get_latest_release():
    url = API_URL.format(repo=GITHUB_REPO)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN_EMBEDDED}",
        "Accept": "application/vnd.github+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def is_newer(release):
    remote_version = release["tag_name"].lstrip("v")
    return Version(remote_version) > Version(__version__)


def find_asset_url(release):
    asset_name = PLATFORM_ASSET_NAMES.get(sys.platform)
    if asset_name is None:
        return None
    for asset in release.get("assets", []):
        if asset["name"] == asset_name:
            return asset["url"]
    return None


def download_asset(asset_url, dest_path):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN_EMBEDDED}",
        "Accept": "application/octet-stream",
    }
    with requests.get(asset_url, headers=headers, stream=True, timeout=30) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(response.raw, f)


def apply_update(new_exe_path):
    # Inside a mounted AppImage, sys.executable points at the temporary
    # squashfs-mounted copy, not the real .AppImage file -- the AppImage
    # runtime sets APPIMAGE to that real path. Unset on Windows/macOS, so
    # this falls back to sys.executable there, same as before.
    current_exe = os.environ.get("APPIMAGE") or sys.executable
    if sys.platform == "win32":
        _apply_update_windows(current_exe, new_exe_path)
    else:
        _apply_update_unix(current_exe, new_exe_path)


def _apply_update_unix(current_exe, new_exe_path):
    os.chmod(new_exe_path, 0o755)
    os.replace(new_exe_path, current_exe)
    os.execv(current_exe, sys.argv)


def _apply_update_windows(current_exe, new_exe_path):
    exe_dir = os.path.dirname(current_exe)
    staged_path = os.path.join(exe_dir, os.path.basename(current_exe) + ".new")
    shutil.move(new_exe_path, staged_path)

    script_path = os.path.join(exe_dir, "_update.bat")
    with open(script_path, "w") as f:
        f.write(
            "@echo off\r\n"
            "ping 127.0.0.1 -n 2 > nul\r\n"
            f'del "{current_exe}"\r\n'
            f'move /y "{staged_path}" "{current_exe}"\r\n'
            f'start "" "{current_exe}"\r\n'
            f'del "%~f0"\r\n'
        )

    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd", "/c", script_path],
        creationflags=DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    sys.exit(0)


def check_and_apply_update():
    """Entry point called from app/main.py on startup. Best-effort: any
    failure (offline, rate-limited, no matching asset) is swallowed so the
    app still launches normally."""
    if not getattr(sys, "frozen", False):
        return  # running from source, not a packaged exe; nothing to replace
    try:
        release = get_latest_release()
        if not is_newer(release):
            return
        asset_url = find_asset_url(release)
        if asset_url is None:
            return
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        download_asset(asset_url, tmp_path)
        apply_update(tmp_path)
    except Exception as exc:
        print(f"Update check failed, continuing without update: {exc}", file=sys.stderr)

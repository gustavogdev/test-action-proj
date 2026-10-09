"""Update-check logic: checks GitHub Releases on the private repo and, if a
newer version exists, prompts the user to update rather than silently
replacing the running binary. Once a release has been out for longer than
UPDATE_GRACE_PERIOD_DAYS, the prompt becomes mandatory (no "Later" option).

Updating always installs the platform installer artifact (.dmg /
installer.exe / .AppImage) the same way a fresh install would -- this repo
never overwrites a running, possibly-signed binary in place.

GITHUB_TOKEN_EMBEDDED and GITHUB_REPO below are placeholders overwritten by
.github/workflows/release.yml at build time (same mechanism as app/_version.py).

Every check (startup or manual) is logged to <data_dir>/updater.log, since
the packaged --windowed build has no visible stdout/stderr.

HTTPS requests are verified against the OS trust store (via `truststore`)
rather than the `certifi` bundle `requests` ships with. On machines behind
a TLS-inspecting proxy, the OS already trusts the proxy's root CA --
certifi's public CA list doesn't, which otherwise makes every HTTPS call
fail with SSLCertVerificationError. This must never be "fixed" by
bundling/exporting a cert from any particular machine into this repo;
relying on the OS trust store is what makes it work on any machine.
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from datetime import datetime, timedelta, timezone

import truststore

truststore.inject_into_ssl()

import requests
from packaging.version import Version

from app._version import __version__
from app.db import get_data_dir

GITHUB_TOKEN_EMBEDDED = "REPLACED_AT_BUILD_TIME"
GITHUB_REPO = "REPLACED_AT_BUILD_TIME"  # "owner/repo"

API_URL = "https://api.github.com/repos/{repo}/releases/latest"

UPDATE_GRACE_PERIOD_DAYS = 7

PLATFORM_ASSET_NAMES = {
    "win32": "myapp-windows-installer.exe",
    "darwin": "myapp-macos-installer.dmg",
    "linux": "myapp-linux-installer.AppImage",
}

logger = logging.getLogger("myapp.updater")
logger.setLevel(logging.INFO)
_log_path = get_data_dir() / "updater.log"
_handler = logging.FileHandler(_log_path)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_handler)


def get_latest_release():
    url = API_URL.format(repo=GITHUB_REPO)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN_EMBEDDED}",
        "Accept": "application/vnd.github+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 401:
        # The embedded token can be missing/stale, but this repo is public,
        # so the Releases API is still readable without any auth at all.
        response = requests.get(
            url, headers={"Accept": "application/vnd.github+json"}, timeout=10
        )
    response.raise_for_status()
    return response.json()


def is_newer(release):
    remote_version = release["tag_name"].lstrip("v")
    return Version(remote_version) > Version(__version__)


def update_deadline(release):
    published_at = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
    return published_at + timedelta(days=UPDATE_GRACE_PERIOD_DAYS)


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


def prompt_update_dialog(current_version, remote_version, deadline, mandatory):
    """Shows a blocking Tk dialog and returns "update", "later", or "quit"."""
    result = {"choice": "quit" if mandatory else "later"}

    root = tk.Tk()
    root.title("Update available")
    root.resizable(False, False)

    deadline_str = deadline.astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [f"A new version is available: v{remote_version} (you have v{current_version})."]
    if mandatory:
        lines.append("This update is required to continue.")
    else:
        lines.append(f"Updates become mandatory on {deadline_str}.")
    message = "\n".join(lines)

    tk.Label(root, text=message, justify="left", padx=20, pady=20).pack()

    button_frame = tk.Frame(root, pady=10)
    button_frame.pack()

    def choose(choice):
        result["choice"] = choice
        root.destroy()

    tk.Button(button_frame, text="Update Now", width=12, command=lambda: choose("update")).pack(
        side="left", padx=5
    )
    if mandatory:
        tk.Button(button_frame, text="Quit", width=12, command=lambda: choose("quit")).pack(
            side="left", padx=5
        )
        root.protocol("WM_DELETE_WINDOW", lambda: choose("quit"))
    else:
        tk.Button(button_frame, text="Later", width=12, command=lambda: choose("later")).pack(
            side="left", padx=5
        )
        root.protocol("WM_DELETE_WINDOW", lambda: choose("later"))

    root.eval("tk::PlaceWindow . center")
    root.mainloop()

    return result["choice"]


def _write_and_launch(script_path, script_body, launch_cmd):
    with open(script_path, "w") as f:
        f.write(script_body)
    os.chmod(script_path, 0o755)
    subprocess.Popen(launch_cmd, close_fds=True, start_new_session=True)


def _install_macos(installer_path, current_exe):
    # current_exe is .../MyApp.app/Contents/MacOS/myapp-macos
    app_bundle = os.path.dirname(os.path.dirname(os.path.dirname(current_exe)))
    apps_dir = os.path.dirname(app_bundle)
    bundle_name = os.path.basename(app_bundle)
    mount_point = tempfile.mkdtemp(prefix="myapp-update-")
    pid = os.getpid()

    script_path = os.path.join(tempfile.gettempdir(), "myapp_update.sh")
    script_body = f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
hdiutil attach {_sh_quote(installer_path)} -mountpoint {_sh_quote(mount_point)} -nobrowse -quiet
rm -rf {_sh_quote(app_bundle)}
cp -R {_sh_quote(mount_point)}/{_sh_quote(bundle_name)} {_sh_quote(apps_dir)}/
hdiutil detach {_sh_quote(mount_point)} -quiet
rm -f {_sh_quote(installer_path)}
open {_sh_quote(app_bundle)}
rm -f "$0"
"""
    _write_and_launch(script_path, script_body, ["/bin/sh", script_path])
    os._exit(0)


def _install_windows(installer_path, current_exe):
    pid = os.getpid()

    script_path = os.path.join(tempfile.gettempdir(), "myapp_update.bat")
    script_body = (
        "@echo off\r\n"
        f":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
        f"if not errorlevel 1 (\r\n"
        f"  ping 127.0.0.1 -n 2 > nul\r\n"
        f"  goto wait\r\n"
        f")\r\n"
        f'"{installer_path}" /S\r\n'
        f'start "" "{current_exe}"\r\n'
        f'del "{installer_path}"\r\n'
        f'del "%~f0"\r\n'
    )
    DETACHED_PROCESS = 0x00000008
    with open(script_path, "w") as f:
        f.write(script_body)
    subprocess.Popen(
        ["cmd", "/c", script_path],
        creationflags=DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    os._exit(0)


def _install_linux(installer_path, current_exe):
    target = os.environ.get("APPIMAGE") or current_exe
    pid = os.getpid()

    script_path = os.path.join(tempfile.gettempdir(), "myapp_update.sh")
    script_body = f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
chmod +x {_sh_quote(installer_path)}
mv {_sh_quote(installer_path)} {_sh_quote(target)}
{_sh_quote(target)} &
rm -f "$0"
"""
    _write_and_launch(script_path, script_body, ["/bin/sh", script_path])
    os._exit(0)


def _sh_quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def install(installer_path):
    current_exe = os.environ.get("APPIMAGE") or sys.executable
    if sys.platform == "win32":
        _install_windows(installer_path, current_exe)
    elif sys.platform == "darwin":
        _install_macos(installer_path, current_exe)
    else:
        _install_linux(installer_path, current_exe)


def check_and_apply_update():
    """Entry point called from app/main.py on startup. Best-effort: a failed
    *check* (offline, rate-limited) is swallowed so the app still launches
    normally. A failed *install* only blocks startup if the update had
    already become mandatory."""
    logger.info("Startup update check: current version is %s", __version__)

    if not getattr(sys, "frozen", False):
        logger.info("Running from source, not a packaged exe; skipping update check")
        return  # running from source, not a packaged exe; nothing to install

    try:
        release = get_latest_release()
    except Exception as exc:
        logger.warning("Startup update check failed, continuing without update: %s", exc)
        return

    remote_version = release["tag_name"].lstrip("v")
    if not is_newer(release):
        logger.info("Startup update check: up to date (latest release is %s)", remote_version)
        return

    logger.info("Startup update check: newer release found: %s", remote_version)
    deadline = update_deadline(release)
    mandatory = datetime.now(timezone.utc) >= deadline

    choice = prompt_update_dialog(__version__, remote_version, deadline, mandatory)
    logger.info("Startup update dialog choice: %s", choice)

    if choice == "later":
        return
    if choice == "quit":
        sys.exit(0)

    try:
        asset_url = find_asset_url(release)
        if asset_url is None:
            raise RuntimeError(f"no release asset for platform {sys.platform!r}")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        download_asset(asset_url, tmp_path)
        logger.info("Downloaded update asset, installing %s", remote_version)
        install(tmp_path)  # dispatches to the platform installer, then exits
    except Exception as exc:
        logger.error("Startup update install failed: %s", exc)
        if mandatory:
            sys.exit(1)


def _set_status(window, message):
    import json

    window.evaluate_js(f"document.getElementById('update-status').textContent = {json.dumps(message)}")


def run_manual_check(window):
    """Entry point for the "Check for Updates" menu item. Runs on a
    pywebview-managed background thread (confirmed in pywebview's cocoa
    backend: menu actions are dispatched via `Thread(...).start()`), so this
    avoids tkinter (main-thread only) and instead uses pywebview's own
    thread-safe `window.evaluate_js`/`window.create_confirmation_dialog`."""
    logger.info("Manual update check requested (current version %s)", __version__)
    _set_status(window, "Checking for updates...")

    try:
        release = get_latest_release()
    except Exception as exc:
        logger.warning("Manual update check failed: %s", exc)
        _set_status(window, f"Update check failed: {exc}")
        return

    remote_version = release["tag_name"].lstrip("v")
    if not is_newer(release):
        logger.info("Manual update check: up to date (latest release is %s)", remote_version)
        _set_status(window, f"Up to date (v{__version__})")
        return

    logger.info("Manual update check: newer release found: %s", remote_version)
    _set_status(window, f"Update available: v{remote_version} (you have v{__version__})")

    if not getattr(sys, "frozen", False):
        logger.info("Running from source; not offering to install %s", remote_version)
        return

    confirmed = window.create_confirmation_dialog(
        "Update available",
        f"A new version is available: v{remote_version} (you have v{__version__}). Update now?",
    )
    logger.info("Manual update dialog choice: %s", "update" if confirmed else "later")
    if not confirmed:
        return

    try:
        asset_url = find_asset_url(release)
        if asset_url is None:
            raise RuntimeError(f"no release asset for platform {sys.platform!r}")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        download_asset(asset_url, tmp_path)
        logger.info("Downloaded update asset, installing %s", remote_version)
        _set_status(window, f"Installing v{remote_version}...")
        install(tmp_path)  # dispatches to the platform installer, then exits
    except Exception as exc:
        logger.error("Manual update install failed: %s", exc)
        _set_status(window, f"Update install failed: {exc}")

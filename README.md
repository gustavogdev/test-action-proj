# myapp

A PyInstaller app with GitHub Actions release automation and a built-in
self-updater that checks this (private) repo's GitHub Releases.

## How the app works

The app is a tiny stdlib-only "click counter" web demo, structured as four
modules under `app/`:

- **`app/main.py`** — entry point. `main()` runs `check_and_apply_update()`
  first, then `run()` initializes the versioned database and starts the
  HTTP server. This is what PyInstaller builds into the packaged executable.
- **`app/server.py`** — a minimal `http.server`-based web server (no
  framework/dependencies) serving one page at `/` that shows a click count
  and a button that `POST`s to `/click` to increment it. All rendering is
  done with simple string templating.
- **`app/db.py`** — versioned SQLite storage. Each released version gets its
  own database file (`clicks_v<version>.db`) in a per-OS data directory (see
  `get_data_dir()`). On every startup it: backs up existing version
  databases to `.bak` files, creates/upgrades the current version's schema
  (additively, from the `SCHEMA` dict), and — if this version's db is brand
  new — copies data forward from the most recent older version's db so click
  history survives upgrades.
- **`app/updater.py`** — the self-updater (see below). Only active in the
  packaged executable (`sys.frozen`); running from source
  (`python -m app.main`) skips it entirely.
- **`app/_version.py`** — holds `__version__`. Checked into source as a dev
  placeholder (`"0.0.0-dev"`) and overwritten at build time to match the
  pushed git tag (see below).

Running locally: `pip install -r requirements.txt && python -m app.main`,
then open `http://127.0.0.1:8765/`.

## Version deployment (git tags → GitHub Releases)

Shipping a new version is entirely driven by pushing an annotated git tag —
there's no manual build or upload step. The flow:

```
git tag v1.2.3
git push origin v1.2.3
```

1. **Tag push triggers the workflow.** Pushing a tag matching `v*.*.*` fires
   `.github/workflows/release.yml`.
2. **Version stamping.** The workflow strips the `v` prefix and writes it into
   `app/_version.py` as `__version__`, so the build and the git tag always
   agree on the version string. This happens fresh on every build — nothing
   is committed back to the repo.
3. **Credential embedding.** The workflow also writes the `UPDATE_READ_TOKEN`
   secret and the `owner/repo` string into `app/updater.py`, replacing the
   `REPLACED_AT_BUILD_TIME` placeholders, so each binary carries its own
   read-only credential for calling the Releases API later.
4. **Build.** PyInstaller builds a `--onefile` executable on Windows, macOS,
   and Linux runners in parallel (matrix build), using the version-stamped,
   credential-embedded source.
5. **Packaging.** Each platform's raw binary is also wrapped into a native
   installer (NSIS `.exe` on Windows, `.dmg` on macOS, AppImage on Linux —
   see `packaging/`).
6. **Release publish.** A GitHub Release is published for the pushed tag with
   six assets: the three raw binaries (`myapp-windows.exe`, `myapp-macos`,
   `myapp-linux` — these are what the self-updater downloads, see below) and
   the three installers (`myapp-windows-installer.exe`,
   `myapp-macos-installer.dmg`, `myapp-linux-installer.AppImage` — these are
   what end users should download for a first install).

Because the version comes solely from the tag, re-pushing a build for the
same version isn't possible without deleting and re-tagging — always bump
the tag for a new build.

## Installing

- **Windows**: run `myapp-windows-installer.exe`. It installs per-user to
  `%LOCALAPPDATA%\Programs\myapp` (no admin/UAC needed) and adds Start Menu /
  Desktop shortcuts. Since the installer is unsigned, SmartScreen will warn
  "Windows protected your PC" — click **More info → Run anyway**.
- **macOS**: open `myapp-macos-installer.dmg` and drag `MyApp.app` to
  Applications (or run it from anywhere). Since the app is unsigned/not
  notarized, Gatekeeper will block a plain double-click the first time —
  right-click the app → **Open** → **Open** to confirm.
- **Linux**: download `myapp-linux-installer.AppImage`, `chmod +x` it, and run
  it directly. No install step; the AppImage is the app.

Uninstalling (Windows: "Add or remove programs", or `uninstall.exe` in the
install directory) leaves each version's SQLite database behind so click
history survives a reinstall — see `app/db.py` for how per-version databases
and schema migrations work.

## One-time setup

Add a repository secret `UPDATE_READ_TOKEN`: a GitHub fine-grained PAT scoped
to **this repository only**, with **Contents: read-only** permission. This is
the credential every shipped binary uses to call the Releases API, since the
repo is private.

## How the self-updater works

On startup (`app/main.py` → `check_and_apply_update()`), the packaged
executable:

1. Calls `GET /repos/<owner>/<repo>/releases/latest` using the embedded token.
2. Compares the release tag against its own built-in version.
3. If newer, downloads the raw per-OS binary (not the installer — the
   installer is only used for the initial install) and replaces itself:
   - macOS/Linux: atomic `os.replace` onto the running binary, then re-exec.
     On Linux this targets the real `.AppImage` file via the `APPIMAGE`
     env var the AppImage runtime sets, not `sys.executable` (which points
     at a temporary mounted copy inside a running AppImage).
   - Windows: stages the new exe, spawns a detached batch script to swap it
     in after this process exits, then exits. Works unmodified against the
     per-user install location.

Running from source (`python -m app.main`) skips the update check entirely —
it only applies to the packaged executable (`sys.frozen`).

## ⚠️ Token rotation runbook

The `UPDATE_READ_TOKEN` is baked into every binary at build time — there is
no way to change a token after it has shipped. This creates a chicken-and-egg
risk: if the embedded PAT is ever revoked, every previously-shipped build
immediately loses the ability to fetch updates (including the update that
would carry the new token).

To rotate safely:

1. Create the **new** PAT first. Do not revoke the old one yet.
2. Update the `UPDATE_READ_TOKEN` secret in GitHub to the new PAT.
3. Cut a new release tag. This ships a build with the new token embedded.
4. Only after you're confident the new build is distributed/adopted, revoke
   the old PAT.

Give the PAT a long expiry so this isn't an emergency on a schedule, and
treat "the token is extractable from the shipped binary by anyone who has
the exe" as a known, accepted tradeoff of this approach (it only grants
read-only access to this repo's contents, nothing else).

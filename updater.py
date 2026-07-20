import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app_paths import get_app_data_dir
from version import __version__

GITHUB_REPO = "ricewas-mis-taken/TypeSense"
_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_INSTALLER_ASSET_NAME = "TypeSenseSetup.exe"
_RELAUNCH_TASK_NAME = "TypeSenseLoggerWatchdog"
_CHECK_INTERVAL_SEC = 24 * 60 * 60
_MIN_INSTALLER_BYTES = 100_000  # sanity floor so a truncated/HTML error response is never executed as an installer


def _log(msg):
	try:
		with open(get_app_data_dir() / "runtime.log", "a", encoding="utf-8") as f:
			f.write(f"{time.ctime()}: [updater] {msg}\n")
	except Exception:
		pass


def _parse_version(v):
	digits_per_part = [
		"".join(ch for ch in part if ch.isdigit())
		for part in v.lstrip("vV").split(".")
	]
	return tuple(int(d) if d else 0 for d in digits_per_part)


def _is_newer(remote_tag, local_version):
	return _parse_version(remote_tag) > _parse_version(local_version)


def _fetch_latest_release():
	req = urllib.request.Request(
		_RELEASES_API,
		headers={"Accept": "application/vnd.github+json", "User-Agent": "TypeSenseLogger-Updater"},
	)
	with urllib.request.urlopen(req, timeout=10) as resp:
		return json.loads(resp.read().decode("utf-8"))


def _download(url, dest):
	req = urllib.request.Request(url, headers={"User-Agent": "TypeSenseLogger-Updater"})
	with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
		f.write(resp.read())


def _unregister_relaunch_task():
	"""The watchdog task can relaunch the old exe mid-install and lock the very
	files the installer is trying to overwrite. Startup re-creates this task
	unconditionally, so it's safe to drop here."""
	subprocess.run(
		["schtasks", "/Delete", "/TN", _RELAUNCH_TASK_NAME, "/F"],
		creationflags=subprocess.CREATE_NO_WINDOW,
		capture_output=True,
	)


def _apply_update(installer_path):
	_unregister_relaunch_task()
	subprocess.Popen(
		[
			str(installer_path),
			"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
			"/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
		],
		creationflags=subprocess.CREATE_NO_WINDOW,
	)
	_log(f"launched installer {installer_path}, exiting for update")
	os._exit(0)


def _check_once():
	release = _fetch_latest_release()
	remote_tag = release.get("tag_name", "")
	if not remote_tag or not _is_newer(remote_tag, __version__):
		return

	asset = next(
		(a for a in release.get("assets", []) if a.get("name") == _INSTALLER_ASSET_NAME),
		None,
	)
	if not asset or not asset.get("browser_download_url"):
		_log(f"newer release {remote_tag} found but no {_INSTALLER_ASSET_NAME} asset attached")
		return

	dest_dir = get_app_data_dir() / "update"
	dest_dir.mkdir(parents=True, exist_ok=True)
	dest = dest_dir / _INSTALLER_ASSET_NAME
	_download(asset["browser_download_url"], dest)

	if not dest.exists() or dest.stat().st_size < _MIN_INSTALLER_BYTES:
		_log(f"downloaded installer for {remote_tag} looked truncated/invalid, skipping update")
		return

	_log(f"updating {__version__} -> {remote_tag}")
	_apply_update(dest)


def _loop():
	while True:
		try:
			_check_once()
		except Exception as e:
			_log(f"check failed: {e!r}")
		time.sleep(_CHECK_INTERVAL_SEC)


def check_for_update_async():
	"""Best-effort background updater: every failure mode here (offline, GitHub
	API changes, a renamed/missing asset, a bad download, ...) is swallowed so
	this can never break the logger it ships inside - including old builds
	that will rely on it to get today's fixes without a manual reinstall."""
	if not getattr(sys, "frozen", False):
		return
	threading.Thread(target=_loop, daemon=True).start()

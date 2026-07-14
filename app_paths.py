import os
from pathlib import Path


def get_app_data_dir() -> Path:
	"""Per-user, always-writable storage dir, independent of where the exe/script lives.

	Autostart (Run key) launches can land in a read-only cwd, and the exe itself may
	sit in a location (Program Files, a Defender-monitored folder, etc.) a standard
	user/process can't write new files into. AppData\\Local is guaranteed writable
	by the owning user account regardless of install location.
	"""
	base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
	data_dir = Path(base) / "TypeSense"
	data_dir.mkdir(parents=True, exist_ok=True)
	return data_dir

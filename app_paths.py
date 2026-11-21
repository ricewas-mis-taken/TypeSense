import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
	"""Per-user, always-writable storage dir, independent of where the exe/script lives.

	On Windows, uses AppData\Local which is guaranteed writable by the owning user.
	On macOS, uses ~/Library/Application Support which is the standard location.
	TYPESENSE_DATA_DIR overrides both (used in tests for isolation).
	"""
	override = os.environ.get("TYPESENSE_DATA_DIR")
	if override:
		data_dir = Path(override)
	elif sys.platform == "darwin":
		data_dir = Path.home() / "Library" / "Application Support" / "TypeSense"
	else:
		base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
		data_dir = Path(base) / "TypeSense"
	data_dir.mkdir(parents=True, exist_ok=True)
	return data_dir

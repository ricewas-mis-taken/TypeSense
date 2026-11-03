"""The one place column lists are defined. The logger, the upload client, the server and
data_comp.py all import from here, so they can never drift apart.

Row layout (v2): metadata (7) + legacy v1 features (11) + new features (29) = 47 columns.
The server adds received_at when it stores a row (48 columns on disk).
"""
from features_v2 import FEATURE_NAMES

SCHEMA_VERSION = "2.0"

# Not features: identify and align the row.
META_COLS = ["schema_version", "session", "boot_id", "wall_start_utc",
			 "ts_ns_start", "gaming_flag", "n_keydowns"]

# The 11 v1 window features, computed by the unchanged v1 code, in their v1 order.
LEGACY_FEATURE_COLS = ["total_press", "total_release", "avg_dwell", "shortest_dwell", "longest_dwell",
					   "avg_flight", "shortest_flight", "longest_flight",
					   "avg_burst", "max_burst", "num_bursts"]

# The 29 new features (avg_dwell_raw / avg_flight_raw are the renamed collisions).
NEW_FEATURE_COLS = list(FEATURE_NAMES)

# All 40 model features (use this for FEATURE_COLS in data_comp.py).
FEATURE_COLS = LEGACY_FEATURE_COLS + NEW_FEATURE_COLS

WINDOW_COLUMNS = META_COLS + FEATURE_COLS                  # what the logger writes and uploads
SERVER_WINDOW_COLUMNS = WINDOW_COLUMNS + ["received_at"]   # what the server stores

# v1 rows (old logger, or queued v1 rows that were never sent): 14 fields, no version tag.
V1_WINDOW_FIELDS = ["session", "time_now"] + LEGACY_FEATURE_COLS + ["gaming"]
V1_SERVER_COLUMNS = V1_WINDOW_FIELDS + ["received_at"]

SURVEY_FIELDS = ["session", "ts_ns", "boot_id", "wall_start_utc", "stress", "focus", "energy", "activity"]
SURVEY_SERVER_COLUMNS = SURVEY_FIELDS + ["received_at"]


def make_window_row(meta, legacy, feats):
	"""Combine the three dicts into one row in WINDOW_COLUMNS order (KeyError if a column is missing)."""
	merged = {**meta, **legacy, **feats}
	return {c: merged[c] for c in WINDOW_COLUMNS}

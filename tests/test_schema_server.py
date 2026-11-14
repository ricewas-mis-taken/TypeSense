"""Tests for schema.py and the server's schema_version validation."""
import importlib, json, os, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import schema
from features_v2 import FEATURE_NAMES


def good_row():
	return {c: (1.5 if c in schema.FEATURE_COLS else "x") for c in schema.WINDOW_COLUMNS} | {
		"schema_version": "2.0", "session": "abc123", "gaming_flag": False}


def test_counts_and_no_duplicates():
	assert len(schema.META_COLS) == 7 and len(schema.LEGACY_FEATURE_COLS) == 11
	assert len(schema.NEW_FEATURE_COLS) == 29 and len(schema.FEATURE_COLS) == 40
	assert len(schema.WINDOW_COLUMNS) == 47 == len(set(schema.WINDOW_COLUMNS))
	assert schema.WINDOW_COLUMNS[7:18] == schema.LEGACY_FEATURE_COLS      # legacy right after meta
	assert schema.WINDOW_COLUMNS[18:] == FEATURE_NAMES                    # then the 29, in order
	assert "avg_dwell" in schema.LEGACY_FEATURE_COLS and "avg_dwell_raw" in schema.NEW_FEATURE_COLS


def test_make_window_row_order_and_missing():
	meta = {c: 0 for c in schema.META_COLS}
	legacy = {c: 0 for c in schema.LEGACY_FEATURE_COLS}
	feats = {c: 0.0 for c in FEATURE_NAMES}
	assert list(schema.make_window_row(meta, legacy, feats)) == schema.WINDOW_COLUMNS
	with pytest.raises(KeyError):
		schema.make_window_row(meta, legacy, {})


@pytest.fixture
def client(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	(tmp_path / "server_config.json").write_text(json.dumps({"secret_token": "t"}))
	sys.modules.pop("client_typesenseML", None)
	srv = importlib.import_module("client_typesenseML")
	return srv.app.test_client(), tmp_path


def post(c, data, path="/data"):
	return c.post(path, json={"token": "t", "data": data})


def test_v2_row_accepted_with_header(client):
	c, tmp = client
	assert post(c, good_row()).status_code == 200
	lines = (tmp / "data_v2" / "abc123.csv").read_text().splitlines()
	assert lines[0].split(",") == schema.SERVER_WINDOW_COLUMNS and len(lines) == 2


def test_v2_wrong_column_count_rejected(client):
	c, tmp = client
	row = good_row()
	del row["rollover_rate"]
	r = post(c, row)
	assert r.status_code == 400 and "rollover_rate" in r.get_json()["error"]
	row = good_row() | {"extra": 1}
	assert post(c, row).status_code == 400
	assert not (tmp / "data_v2" / "abc123.csv").exists()


def test_v2_non_numeric_feature_rejected(client):
	c, _ = client
	assert post(c, good_row() | {"avg_dwell_raw": "a"}).status_code == 400


def test_bad_or_unknown_version_rejected(client):
	c, _ = client
	assert post(c, good_row() | {"schema_version": "3.0"}).status_code == 400
	assert post(c, good_row() | {"schema_version": "2.1"}).status_code == 400


def test_v1_untagged_and_tagged_go_to_legacy(client):
	c, tmp = client
	v1 = {k: 1 for k in schema.V1_WINDOW_FIELDS} | {"session": "abc123"}
	assert post(c, v1).status_code == 200                          # old logger: no version tag
	assert post(c, v1 | {"schema_version": "1.x"}).status_code == 200   # tagged by the queue
	lines = (tmp / "data_legacy" / "abc123.csv").read_text().splitlines()
	assert lines[0].split(",") == schema.V1_SERVER_COLUMNS and len(lines) == 3
	assert not (tmp / "data_v2" / "abc123.csv").exists()
	assert post(c, {"session": "abc123"}).status_code == 400       # v1 missing columns


def test_survey_with_and_without_boot_id(client):
	c, tmp = client
	s = {"session": "abc123", "ts_ns": 5, "stress": 3, "focus": 4, "energy": 5, "activity": "Coding"}
	assert post(c, s, "/survey").status_code == 200                                # old queued survey
	assert post(c, s | {"boot_id": "ab12", "wall_start_utc": "2026-01-01T00:00:00.000Z"}, "/survey").status_code == 200
	lines = (tmp / "surveys_v2" / "abc123.csv").read_text().splitlines()
	assert lines[0].split(",") == schema.SURVEY_SERVER_COLUMNS and len(lines) == 3

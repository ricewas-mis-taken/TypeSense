"""Tests for features_v2.compute_window_features, using hand-built event streams."""
import inspect, math, os, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import features_v2
from features_v2 import FEATURE_NAMES, compute_window_features

MS = 1_000_000
WIN = 15_000 * MS


def stream(keys):
	"""keys: list of (press_ms, dwell_ms, cat) -> event tuples (press + release)."""
	ev = []
	for p, d, cat in keys:
		ev.append(("press", p * MS, cat, None))
		ev.append(("release", (p + d) * MS, cat, d * MS))
	return ev


def test_names_count_and_unique():
	assert len(FEATURE_NAMES) == 29 and len(set(FEATURE_NAMES)) == 29


def test_known_values():
	# 5 keys: presses at 0,100,200,500,3500 ms (flights 100,100,300,3000), dwell 80 each.
	cats = [0, 3, 3, 2, 4]
	f = compute_window_features(stream([(t, 80, c) for t, c in zip([0, 100, 200, 500, 3500], cats)]), 0)
	assert f["avg_dwell_raw"] == pytest.approx(80) and f["sd_dwell"] == pytest.approx(0)
	assert f["median_dwell"] == pytest.approx(80)
	assert f["avg_flight_raw"] == pytest.approx(875)
	assert f["sd_flight"] == pytest.approx(math.sqrt(sum((x - 875) ** 2 for x in [100, 100, 300, 3000]) / 4))
	assert f["cv_flight"] == pytest.approx(f["sd_flight"] / 875)
	assert f["pause_rate"] == pytest.approx(2 / 5)          # 300 and 3000
	assert f["avg_pause"] == pytest.approx(1650)
	assert f["long_pause_rate"] == pytest.approx(1 / 5)      # 3000 only
	assert f["max_pause"] == pytest.approx(3000)
	assert f["idle_frac"] == pytest.approx(3000 / 15000)
	assert f["backspace_rate"] == pytest.approx(2 / 5)
	assert f["enter_rate"] == pytest.approx(1 / 5) and f["space_rate"] == pytest.approx(1 / 5)
	assert f["keys_per_min"] == pytest.approx(20)
	assert f["median_flight"] == pytest.approx(200)
	assert f["p10_flight"] == pytest.approx(100) and f["p90_flight"] == pytest.approx(2190)
	assert f["backspace_run_rate"] == pytest.approx(4)       # one run of 2, per minute = 1 / 0.25
	assert f["rollover_rate"] == 0
	# flights 100,100,300,3000: only the first two are < 150 -> 1 burst of 3 keys
	assert f["burst_count"] == 1 and f["avg_burst_len"] == pytest.approx(3)
	assert f["digit_rate"] == f["ctrl_rate"] == f["alt_rate"] == 0


def test_exactly_five_vs_four_keydowns():
	keys = [(i * 100, 50, 0) for i in range(5)]
	assert compute_window_features(stream(keys), 0) is not None
	stats = {}
	assert compute_window_features(stream(keys[:4]), 0, stats=stats) is None
	assert stats["skipped"] == 1


def test_all_backspaces():
	f = compute_window_features(stream([(i * 100, 50, 3) for i in range(6)]), 0)
	assert f["backspace_rate"] == 1.0
	assert f["backspace_run_rate"] == pytest.approx(4)       # one run, 4 per minute


def test_huge_pause():
	keys = [(0, 50, 0), (100, 50, 0), (200, 50, 0), (300, 50, 0), (14_900, 50, 0)]
	f = compute_window_features(stream(keys), 0)
	assert f["max_pause"] == pytest.approx(14_600)
	assert f["idle_frac"] == pytest.approx(14_600 / 15_000)
	assert 0 <= f["idle_frac"] <= 1


def test_rollover():
	# key 2 goes down at 100 ms while key 1 (held 150 ms) is still down; others don't overlap.
	keys = [(0, 150, 0), (100, 50, 0), (300, 50, 0), (500, 50, 0), (700, 50, 0)]
	f = compute_window_features(stream(keys), 0)
	assert f["rollover_rate"] == pytest.approx(1 / 5)


def test_window_edge():
	# Presses before/after the window are ignored; a key pressed in the window but
	# released after the window end still gets its dwell.
	start = 20_000
	keys = [(start - 50, 10, 0)] + [(start + i * 100, 40, 0) for i in range(5)] + [(start + 15_000 + 10, 10, 0)]
	keys[5] = (start + 14_990, 100, 0)  # released 90 ms after the window ends
	keys.sort()
	f = compute_window_features(stream(keys), start * MS)
	assert f["keys_per_min"] == pytest.approx(5 * 4)
	assert f["max_pause"] == pytest.approx(14_690)           # presses at +0,+100,+200,+300,+14990
	assert f["avg_dwell_raw"] == pytest.approx((40 * 4 + 100) / 5)


def test_flights_do_not_cross_windows():
	# 5 keys in window 2 only; a key in window 1 must not create a flight into window 2.
	keys = [(100, 50, 0)] + [(15_500 + i * 100, 50, 0) for i in range(5)]
	f = compute_window_features(stream(keys), WIN)
	assert f["max_pause"] == pytest.approx(100)


def test_undefined_metrics_are_zero_not_nan():
	# identical flights: sd 0, zero-variance autocorr; 5 keys -> only 4 flights.
	f = compute_window_features(stream([(i * 100, 50, 0) for i in range(5)]), 0)
	for v in f.values():
		assert isinstance(v, float) and math.isfinite(v)
	assert f["flight_autocorr"] == 0.0 and f["avg_pause"] == 0.0 and f["burst_count"] == 1


def test_autocorr_alternating():
	# flights alternate 100,300,100,300 -> strongly negative lag-1 autocorrelation
	t, keys = 0, [(0, 50, 0)]
	for fl in [100, 300, 100, 300, 100]:
		t += fl
		keys.append((t, 50, 0))
	f = compute_window_features(stream(keys), 0)
	assert f["flight_autocorr"] < -0.5


def test_privacy_output_is_29_numbers_only():
	f = compute_window_features(stream([(i * 100, 50, i % 13) for i in range(20)]), 0)
	assert list(f) == FEATURE_NAMES and len(f) == 29
	assert all(isinstance(v, float) for v in f.values())
	assert not any(isinstance(v, str) for v in f.values())


def test_privacy_module_never_touches_key_content():
	# The module may only import math, and must never read a key's character or do file I/O.
	import ast
	tree = ast.parse(inspect.getsource(features_v2))
	imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
	assert imported == {"math"}
	assert not any(isinstance(n, ast.Attribute) and n.attr == "char" for n in ast.walk(tree))
	assert not any(isinstance(n, ast.Name) and n.id == "open" for n in ast.walk(tree))


@pytest.mark.skipif("TYPESENSE_RAW_LOG" not in os.environ, reason="set TYPESENSE_RAW_LOG to a raw keyrecsimp_*.csv")
def test_real_raw_log_runs_clean():
	"""Run the extractor over a real raw log (never copied into the repo): every row finite."""
	import csv
	by_boot_window = {}
	with open(os.environ["TYPESENSE_RAW_LOG"], newline="") as fh:
		for row in csv.DictReader(fh):
			ts = int(row["ts_ns"])
			dwell = int(row["dwell_time"]) if row["dwell_time"] else None
			by_boot_window.setdefault(ts // WIN, []).append((row["event"], ts, int(row["cat"]), dwell))
	good = 0
	for w, ev in by_boot_window.items():
		f = compute_window_features(ev, w * WIN)
		if f:
			good += 1
			assert all(math.isfinite(v) for v in f.values())
	assert good > 0

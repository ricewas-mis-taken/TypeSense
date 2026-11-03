"""Tests for align.py: anchors file and ts_ns -> wall-clock mapping, incl. a simulated reboot."""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import align

S = 1_000_000_000


def test_utc_iso_ms():
	assert align.utc_iso_ms(1_700_000_000 * S + 123_456_789) == "2023-11-14T22:13:20.123Z"


def test_write_and_load_anchor(tmp_path):
	p = tmp_path / "anchors_x.csv"
	align.write_anchor(p, "abcd1234")
	align.write_anchor(p, "abcd1234")
	rows = align.load_anchors(p)
	assert len(rows) == 2 and rows[0][0] == "abcd1234"
	assert rows[1][1] > rows[0][1] and abs(rows[0][2] - time.time_ns()) < 5 * S
	assert p.read_text().splitlines()[0] == "boot_id,perf_ns,wall_utc_ns"


def test_simulated_reboot_and_restart():
	# Boot A: perf 1000 s, wall 5000 s offset. Logger restarted (new boot_id, same boot).
	# Boot B (after reboot): perf counter resets to ~10 s, wall is much later.
	W = 1_700_000_000 * S
	anchors = [
		("a1", 1000 * S, W + 0),            # boot A, process 1
		("a1", 1060 * S, W + 60 * S),
		("a2", 1500 * S, W + 500 * S),      # boot A, process 2 (restart; same offset)
		("b1", 10 * S, W + 90_000 * S),     # boot B, perf reset
		("b1", 70 * S, W + 90_060 * S),
	]
	ts = [1010 * S, 1075 * S,        # process 1 (second after the 1060 s anchor)
		  1505 * S,                  # process 2
		  12 * S, 80 * S]            # after reboot: ts went backwards
	out = align.align_events(ts, anchors)
	assert out == [W + 10 * S, W + 75 * S, W + 505 * S, W + 90_002 * S, W + 90_070 * S]


def test_no_anchors():
	assert align.align_events([1, 2], []) == [None, None]

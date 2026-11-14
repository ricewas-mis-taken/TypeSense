"""Boot-proof timestamps for TypeSense.

perf_counter_ns restarts at every boot, so raw-log ts_ns values from different boots
can't be compared. The logger therefore writes anchors_<session>.csv: rows of
(boot_id, perf_ns, wall_utc_ns) taken at startup and every 60 s. This module writes
those rows and maps raw ts_ns values back to wall-clock UTC.

Pure standard library, so the logger and offline analysis scripts can both import it.
"""
import csv, os, time
from datetime import datetime, timezone

ANCHOR_HEADER = ["boot_id", "perf_ns", "wall_utc_ns"]
ANCHOR_INTERVAL_SEC = 60
# An event further than this past a boot's last anchor belongs to a later boot.
SLACK_NS = 120 * 1_000_000_000


def utc_iso_ms(wall_utc_ns):
	"""Wall-clock ns since the epoch -> ISO-8601 UTC string, millisecond precision."""
	dt = datetime.fromtimestamp(wall_utc_ns // 1_000_000_000, tz=timezone.utc)
	ms = (wall_utc_ns // 1_000_000) % 1000
	return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def wall_ns_for_perf(perf_ns):
	"""Wall-clock UTC ns for a perf_counter_ns value from this boot (now-relative)."""
	return time.time_ns() - (time.perf_counter_ns() - perf_ns)


def write_anchor(path, boot_id):
	"""Append one (boot_id, perf_ns, wall_utc_ns) row, then flush and fsync it."""
	is_new = not os.path.exists(path)
	perf = time.perf_counter_ns()
	wall = time.time_ns()  # sampled right after perf so the pair is as close as possible
	with open(path, "a", newline="", encoding="utf-8") as f:
		w = csv.writer(f)
		if is_new:
			w.writerow(ANCHOR_HEADER)
		w.writerow([boot_id, perf, wall])
		f.flush()
		os.fsync(f.fileno())


def load_anchors(path):
	"""Read anchors_<session>.csv -> list of (boot_id, perf_ns, wall_utc_ns), file order."""
	with open(path, newline="", encoding="utf-8") as f:
		return [(r["boot_id"], int(r["perf_ns"]), int(r["wall_utc_ns"])) for r in csv.DictReader(f)]


def align_events(ts_list, anchors):
	"""Map raw-log ts_ns values (in file order) to wall-clock UTC ns.

	The raw log has no boot id, so boots are found from the anchors (grouped by boot_id,
	in file order). Moving through the events in order, we advance to the next boot when
	ts_ns goes backwards (perf counter reset) or jumps well past the current boot's last
	anchor (logger restarted on the same boot). Within a boot each event uses the latest
	anchor at or before it. Returns a list of wall_utc_ns, None where no anchor exists.
	Limit: after a sleep/resume, events before the next anchor can be off by the sleep length.
	"""
	groups = []  # one list of (perf_ns, wall_ns) per boot_id run
	for boot_id, perf, wall in anchors:
		if not groups or groups[-1][0] != boot_id:
			groups.append((boot_id, []))
		groups[-1][1].append((perf, wall))
	if not groups:
		return [None] * len(ts_list)

	out, g, prev = [], 0, None
	for ts in ts_list:
		while g + 1 < len(groups) and (
			(prev is not None and ts < prev) or ts > groups[g][1][-1][0] + SLACK_NS
		):
			g += 1
		prev = ts
		pts = groups[g][1]
		best = pts[0]
		for p in pts:  # anchors are few (1/min), a linear scan is fine
			if p[0] <= ts:
				best = p
			else:
				break
		out.append(best[1] + (ts - best[0]))
	return out

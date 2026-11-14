"""TypeSense v2 window feature extractor.

Pure functions only: no file I/O, no pynput, no globals. Safe to import from the
logger and from offline analysis scripts.

PRIVACY: the input carries only timing and the coarse category code (cat 0-12),
never a key's content, and the output is 29 plain numbers.

Input events are tuples (event, ts_ns, cat, dwell_ns), the same fields as the raw log:
  event    "press" or "release"
  ts_ns    perf_counter_ns timestamp
  cat      category code 0-12
  dwell_ns on release rows: hold time in ns (-1 if unknown); ignored on press rows

The raw log has no key identity, so a release is matched to its press by
press_time = release_ts - dwell. Pass in the window's events plus any release
events slightly after the window end, so keys held across the edge still get
their dwell.
"""
import math

WINDOW_LEN_NS = 15_000_000_000
MIN_KEYDOWNS = 5

# Output order of the 29 features (this is the column order used downstream).
FEATURE_NAMES = [
	# core timing (13)
	"avg_dwell_raw", "sd_dwell", "avg_flight_raw", "sd_flight", "cv_flight",
	"pause_rate", "avg_pause", "backspace_rate", "enter_rate", "shift_rate",
	"arrow_rate", "punct_rate", "keys_per_min",
	# timing shape (6)
	"median_dwell", "median_flight", "p10_flight", "p90_flight",
	"flight_autocorr", "rollover_rate",
	# pauses and bursts (5)
	"long_pause_rate", "max_pause", "idle_frac", "burst_count", "avg_burst_len",
	# corrections (1)
	"backspace_run_rate",
	# key mix (4)
	"digit_rate", "space_rate", "ctrl_rate", "alt_rate",
]

# Category codes used below (see categorize() in keylogger.py).
CAT_DIGIT, CAT_SPACE, CAT_BACKSPACE, CAT_ENTER, CAT_SHIFT = 1, 2, 3, 4, 5
CAT_CTRL, CAT_ALT, CAT_ARROW, CAT_PUNCT = 6, 7, 8, 12

PAUSE_MS = 200        # a flight longer than this is a "pause"
LONG_PAUSE_MS = 2000
IDLE_MS = 1000
BURST_FLIGHT_MS = 150  # flights shorter than this keep a burst going
BURST_MIN_KEYS = 3
BACKSPACE_RUN_MIN = 2

# Standard deviation uses the population formula (divide by n). Set to 1 for sample.
SD_DDOF = 0


def _mean(xs):
	return sum(xs) / len(xs) if xs else 0.0


def _sd(xs):
	n = len(xs)
	if n - SD_DDOF <= 0:
		return 0.0
	m = _mean(xs)
	return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - SD_DDOF))


def _percentile(xs, p):
	"""Linear-interpolation percentile (same as numpy's default). p in 0-100."""
	if not xs:
		return 0.0
	s = sorted(xs)
	pos = (len(s) - 1) * p / 100
	lo = int(math.floor(pos))
	hi = min(lo + 1, len(s) - 1)
	return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _autocorr_lag1(xs):
	"""Lag-1 autocorrelation; 0 if fewer than 4 values or no variance."""
	if len(xs) < 4:
		return 0.0
	m = _mean(xs)
	den = sum((x - m) ** 2 for x in xs)
	if den == 0:
		return 0.0
	num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(len(xs) - 1))
	return num / den


def _runs(flags):
	"""Lengths of consecutive True runs in a list of booleans."""
	out, n = [], 0
	for f in flags:
		if f:
			n += 1
		elif n:
			out.append(n)
			n = 0
	if n:
		out.append(n)
	return out


def compute_window_features(events, window_start_ns, window_len_ns=WINDOW_LEN_NS, stats=None):
	"""Return the 29 features for one window as a dict, or None if the window has
	fewer than MIN_KEYDOWNS keydowns. If `stats` (a dict) is given, the number of
	skipped windows is counted in stats["skipped"]."""
	window_end_ns = window_start_ns + window_len_ns

	# Keydowns that start inside the window, in time order: (ts_ns, cat).
	downs = sorted(
		(ts, cat) for ev, ts, cat, _ in events
		if ev == "press" and window_start_ns <= ts < window_end_ns
	)
	n = len(downs)
	if n < MIN_KEYDOWNS:
		if stats is not None:
			stats["skipped"] = stats.get("skipped", 0) + 1
		return None

	# press_ts -> release_ts, rebuilt from release rows (release_ts - dwell = press_ts).
	release_of = {}
	for ev, ts, _, dwell in events:
		if ev == "release" and dwell is not None and dwell >= 0:
			release_of[ts - dwell] = ts

	# Dwell (ms) of the keys pressed in this window.
	dwells = [(release_of[t] - t) / 1e6 for t, _ in downs if t in release_of]

	# Flight (ms) = gap between consecutive keydowns, inside the window only.
	flights = [(downs[i][0] - downs[i - 1][0]) / 1e6 for i in range(1, n)]

	cats = [c for _, c in downs]
	pauses = [f for f in flights if f > PAUSE_MS]
	minutes = window_len_ns / 60e9

	# Rollover: this key went down before the previous key was released.
	rollovers = 0
	for i in range(1, n):
		prev_release = release_of.get(downs[i - 1][0])
		if prev_release is not None and prev_release > downs[i][0]:
			rollovers += 1

	# Bursts: maximal runs of flights < 150 ms. A run of k flights is k+1 keydowns.
	burst_keys = [k + 1 for k in _runs([f < BURST_FLIGHT_MS for f in flights])
				  if k + 1 >= BURST_MIN_KEYS]

	avg_flight = _mean(flights)
	sd_flight = _sd(flights)

	def rate(cat):
		return cats.count(cat) / n

	feats = {
		"avg_dwell_raw": _mean(dwells),
		"sd_dwell": _sd(dwells),
		"avg_flight_raw": avg_flight,
		"sd_flight": sd_flight,
		"cv_flight": sd_flight / avg_flight if avg_flight > 0 else 0.0,
		"pause_rate": len(pauses) / n,
		"avg_pause": _mean(pauses),
		"backspace_rate": rate(CAT_BACKSPACE),
		"enter_rate": rate(CAT_ENTER),
		"shift_rate": rate(CAT_SHIFT),
		"arrow_rate": rate(CAT_ARROW),
		"punct_rate": rate(CAT_PUNCT),
		"keys_per_min": n * (60000 / (window_len_ns / 1e6)),
		"median_dwell": _percentile(dwells, 50),
		"median_flight": _percentile(flights, 50),
		"p10_flight": _percentile(flights, 10),
		"p90_flight": _percentile(flights, 90),
		"flight_autocorr": _autocorr_lag1(flights),
		"rollover_rate": rollovers / n,
		"long_pause_rate": sum(1 for f in flights if f > LONG_PAUSE_MS) / n,
		"max_pause": max(flights),
		"idle_frac": min(1.0, sum(f for f in flights if f > IDLE_MS) / (window_len_ns / 1e6)),
		"burst_count": float(len(burst_keys)),
		"avg_burst_len": _mean(burst_keys),
		"backspace_run_rate": len([r for r in _runs([c == CAT_BACKSPACE for c in cats])
								   if r >= BACKSPACE_RUN_MIN]) / minutes,
		"digit_rate": rate(CAT_DIGIT),
		"space_rate": rate(CAT_SPACE),
		"ctrl_rate": rate(CAT_CTRL),
		"alt_rate": rate(CAT_ALT),
	}
	# Plain floats, in the documented column order.
	return {name: float(feats[name]) for name in FEATURE_NAMES}

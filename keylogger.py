import csv, time, uuid, statistics, json
from pathlib import Path
from pynput.keyboard import Key, Listener
import user_send
import tkinter as tk
from tkinter import messagebox, simpledialog
from survey import show_survey, SURVEY_INTERVAL_SEC, show_mode_reminder
import threading
import os
import sys
import platform
import subprocess
from PIL import Image, ImageDraw
from app_paths import get_app_data_dir
import align
import schema
import features_v2

if sys.platform != "darwin":
	import winreg
	import ctypes
	import pystray
else:
	import pystray  # still imported so the tray_icon() function parses; guarded before run()

# --- passcode gate ---
if getattr(sys, "frozen", False):
	_config_dir = Path(sys.executable).parent
else:
	_config_dir = Path(__file__).parent
_participant_passcode = None  # None = no local passcode; the server validates what the participant types
try:
	_cfg = json.loads((_config_dir / "config.json").read_text())
	_participant_passcode = _cfg.get("participant_passcode", "password")
except Exception:
	pass


RELAUNCH_CHECK_INTERVAL_MIN = 20
RELAUNCH_TASK_NAME = "TypeSenseLoggerWatchdog"

dnd_enabled = threading.Event()
gaming_enabled = threading.Event()


def _log_event(msg):
	"""The packaged exe is built --noconsole, so print() output has nowhere to
	go - without this, crashes and errors that don't happen at startup leave
	no trace to diagnose later."""
	try:
		with open(get_app_data_dir() / "runtime.log", "a", encoding="utf-8") as f:
			f.write(f"{time.ctime()}: {msg}\n")
	except Exception:
		pass


def _create_mutex(name):
	"""Win32 named mutex enforcing a single running instance. Error 183 is
	ERROR_ALREADY_EXISTS (another instance holds it, so exit immediately);
	any other failure can't guarantee single-instance, but exiting here would
	be worse than just logging and continuing with a second process."""
	if sys.platform == "darwin":
		return None
	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	mutex = kernel32.CreateMutexW(None, False, name)
	if not mutex:
		_log_event(f"[_create_mutex] CreateMutexW failed, error={ctypes.get_last_error()}")
	elif ctypes.get_last_error() == 183:
		os._exit(0)
	return mutex


_single_instance_mutex = _create_mutex("Global\\TypeSenseLogger_SingleInstance_Mutex")


def _running_packaged():
	"""True for an MSIX/Desktop Bridge install. Confirmed by testing: a
	packaged full-trust process's own HKCU\\...\\Run write silently does not
	register real autostart (no error, but the key is never actually updated) -
	so there's no point attempting it there. WindowsApps is where every MSIX
	package's per-user install lands; nothing else installs there."""
	return "\\WindowsApps\\" in sys.executable


def ensure_autostart():
	if not getattr(sys, "frozen", False):
		return
	if sys.platform == "darwin":
		launchd_path = Path.home() / "Library" / "LaunchAgents" / "com.typesense.logger.plist"
		launchd_path.parent.mkdir(parents=True, exist_ok=True)
		plist_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.typesense.logger</string>
	<key>ProgramArguments</key>
	<array>
		<string>/Applications/TypeSense.app/Contents/MacOS/TypeSense</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>/tmp/com.typesense.logger.stdout</string>
	<key>StandardErrorPath</key>
	<string>/tmp/com.typesense.logger.stderr</string>
</dict>
</plist>'''
		launchd_path.write_text(plist_content)
		subprocess.run(["launchctl", "load", str(launchd_path)], capture_output=True)
		return
	if _running_packaged():
		# AppxManifest.xml's uap5:StartupTask (Enabled="true") handles this
		# instead - Windows registers it for real the first time the packaged
		# app launches, no runtime API call needed on this side.
		return
	exe_path = sys.executable
	run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
	try:
		key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_ALL_ACCESS)
	except FileNotFoundError:
		key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key)

	try:
		existing, _ = winreg.QueryValueEx(key, "TypeSenseLogger")
	except FileNotFoundError:
		existing = None

	desired = f'"{exe_path}"'
	if existing != desired:
		winreg.SetValueEx(key, "TypeSenseLogger", 0, winreg.REG_SZ, desired)
	winreg.CloseKey(key)


def ensure_relaunch_task():
	"""Registers a per-user Scheduled Task that periodically tries to launch
	the logger. If it's already running, the single-instance mutex makes the
	new attempt exit immediately, so this never produces a second lasting
	process - it only relaunches the logger after an accidental close, quit,
	or crash left it not running."""
	if sys.platform == "darwin":
		return  # launchd KeepAlive in the plist handles this on macOS
	if not getattr(sys, "frozen", False):
		return
	exe_path = sys.executable
	result = subprocess.run(
		[
			"schtasks", "/Create", "/F",
			"/TN", RELAUNCH_TASK_NAME,
			"/TR", f'"{exe_path}"',
			"/SC", "MINUTE",
			"/MO", str(RELAUNCH_CHECK_INTERVAL_MIN),
		],
		creationflags=subprocess.CREATE_NO_WINDOW,
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		_log_event(f"[ensure_relaunch_task] schtasks failed ({result.returncode}): {result.stderr.strip()}")


def _check_macos_accessibility_permission():
	if sys.platform != "darwin":
		return True
	try:
		result = subprocess.run(
			["osascript", "-e", 'tell application "System Events" to get UI elements'],
			capture_output=True, timeout=2,
		)
		if result.returncode == 0:
			return True
	except Exception:
		pass
	messagebox.showwarning(
		"Accessibility Permission Required",
		"TypeSense needs Accessibility permission to capture keystrokes.\n\n"
		"System Settings → Privacy & Security → Accessibility\n\n"
		"Add 'TypeSense' and re-launch the app.")
	return False


def categorize(key):
	try:
		char = key.char
		if char and char.isalpha(): return 0
		if char and char.isdigit(): return 1
		return 12
	except AttributeError:
		if key == Key.space: return 2
		elif key == Key.backspace: return 3
		elif key == Key.enter: return 4
		elif key in (Key.shift, Key.shift_r): return 5
		elif key in (Key.ctrl, Key.ctrl_r): return 6
		elif key in (Key.alt, Key.alt_r): return 7
		elif key in (Key.up, Key.down, Key.left, Key.right): return 8
		elif str(key).startswith("Key.f"): return 9
		elif key == Key.esc: return 10
		return 11

# Below this, a window's dwell/flight averages are too noisy (too few samples)
# to trust - both for the CSV row and for counting the window as "active" below.
MIN_KEYSTROKES_PER_WINDOW = 15

WINDOW_COLUMNS = schema.WINDOW_COLUMNS

class Simplekeylog:
	def __init__(self, out_dir = None, window_sec = 15):
		self.session_id = self._load_or_create_session_id()
		self.out_dir = Path(out_dir) if out_dir else (get_app_data_dir() / "simple_data")
		self.out_dir.mkdir(parents=True, exist_ok=True)

		self.log_file = self.out_dir / f"keyrecsimp_{self.session_id}.csv"
		self.window_file = self.out_dir / f"importantsimp_{self.session_id}.csv"

		self._rotate_stale_window_file()

		kf_is_new = not self.log_file.exists()
		ff_is_new = not self.window_file.exists()

		self._kf = open(self.log_file, "a", newline='', encoding="utf-8")
		self._ff_file = open(self.window_file, "a", newline='', encoding="utf-8")

		self._ff = csv.writer(self._ff_file)
		self._kw = csv.writer(self._kf)

		if kf_is_new:
			self._kw.writerow(["session","ts_ns","event", "cat", "dwell_time"])
		if ff_is_new:
			self._ff.writerow(WINDOW_COLUMNS)

		self.boot_id = uuid.uuid4().hex[:8]
		self.anchor_file = self.out_dir / f"anchors_{self.session_id}.csv"
		align.write_anchor(self.anchor_file, self.boot_id)
		threading.Thread(target=self._anchor_loop, daemon=True).start()

		self.events = []
		self.all_dwell = []
		self.all_flight = []
		self._press_times = {}

		self._last_press_ns = None

		self.window_sec = window_sec
		self.window_start_ns = time.perf_counter_ns()
		self.total_press =0
		self.total_release = 0


		self.window_press = 0
		self.window_release = 0

		self.active_window_count = 0
		self.last_keystroke_ts = None

	def _anchor_loop(self):
		while True:
			time.sleep(align.ANCHOR_INTERVAL_SEC)
			try:
				align.write_anchor(self.anchor_file, self.boot_id)
			except Exception as e:
				_log_event(f"[anchor] error: {e!r}")

	def _rotate_stale_window_file(self):
		"""The window CSV schema changed in 2.0.0. Appending new-schema rows to an
		old-schema file would misalign columns, so a mismatched header means the
		old file is renamed to *_v1.csv (never overwritten) and a fresh one starts."""
		if not self.window_file.exists():
			return
		try:
			with open(self.window_file, "r", newline='', encoding="utf-8") as f:
				header = next(csv.reader(f), [])
		except Exception as e:
			_log_event(f"[rotate] could not read window file header: {e!r}")
			return
		if header == WINDOW_COLUMNS:
			return
		if not header:
			return  # empty file; the header gets written normally
		target = self.window_file.with_name(self.window_file.stem + "_v1.csv")
		n = 1
		while target.exists():
			n += 1
			target = self.window_file.with_name(f"{self.window_file.stem}_v1_{n}.csv")
		os.replace(self.window_file, target)
		_log_event(f"[rotate] old-schema window file moved to {target.name}")

	def _load_or_create_session_id(self):
		id_file = get_app_data_dir() / "participant_id.txt"
		if id_file.exists():
			existing = id_file.read_text().strip()
			if existing:
				self.is_first_run = False
				return existing
		new_id = str(uuid.uuid4())[:8]
		id_file.write_text(new_id)
		self.is_first_run = True
		return new_id

	def _jarvis(self, values):
		valid = [v for v in values if 10_000_000<v<300_000_000]
		if not valid:
			return -1,-1,-1
		return (
			round(sum(valid) / len(valid) /1e6,3),
			round  (min(valid) / 1e6,3),
			round (max(valid) / 1e6,3),
		)



	def _compute_burst(self, threshold_ns = 200_000_000):
		if not self.all_flight:
			return [1]
		current_burst =1
		burst_lens = []
		for flight_ns in self.all_flight:
			if flight_ns > threshold_ns:
				burst_lens.append(current_burst)
				current_burst = 1
			else:
				current_burst +=1
		burst_lens.append(current_burst)
		return burst_lens

	@staticmethod
	def _spread(valid_ms):
		"""(sd, median, iqr) of a list of ms values; -1s when too few samples."""
		if len(valid_ms) < 2:
			med = round(valid_ms[0], 3) if valid_ms else -1
			return -1, med, -1
		sd = round(statistics.stdev(valid_ms), 3)
		med = round(statistics.median(valid_ms), 3)
		if len(valid_ms) < 4:
			return sd, med, -1
		q = statistics.quantiles(valid_ms, n=4)
		return sd, med, round(q[2] - q[0], 3)

	@staticmethod
	def _valid_ms(values):
		return [v / 1e6 for v in values if 10_000_000 < v < 300_000_000]

	def _write_window_row(self, now):

		avg_d, min_d, max_d = self._jarvis(self.all_dwell)
		avg_f, min_f, max_f = self._jarvis(self.all_flight)
		sd_d, med_d, iqr_d = self._spread(self._valid_ms(self.all_dwell))
		sd_f, med_f, iqr_f = self._spread(self._valid_ms(self.all_flight))
		cv_f = round(sd_f / avg_f, 3) if sd_f >= 0 and avg_f > 0 else -1

		flights = [f for f in self.all_flight if f > 0]
		pauses = [f / 1e6 for f in flights if f > 200_000_000]
		pause_rate = round(len(pauses) / len(flights), 4) if flights else 0
		avg_pause = round(sum(pauses) / len(pauses), 3) if pauses else -1
		max_pause = round(max(pauses), 3) if pauses else -1

		burst_lens = self._compute_burst()
		avg_burst = round(sum(burst_lens) / len(burst_lens), 2)
		max_burst = max(burst_lens)
		num_burst = len(burst_lens)

		press_cats = [e[2] for e in self.events if e[0] == "press"]
		n_press = len(press_cats)
		def rate(cat):
			return round(press_cats.count(cat) / n_press, 4) if n_press else 0
		total_corr = press_cats.count(3)
		run = max_run = 0
		for c in press_cats:
			run = run + 1 if c == 3 else 0
			max_run = max(max_run, run)
		elapsed_min = (now - self.window_start_ns) / 60e9
		keys_per_min = round(n_press / elapsed_min, 2) if elapsed_min > 0 else 0

		row = {
			"session": self.session_id,
			"time_now": now,
			"total_press": self.total_press,
			"total_release": self.total_release,
			"avg_dwell": avg_d,
			"sd_dwell": sd_d,
			"median_dwell": med_d,
			"iqr_dwell": iqr_d,
			"shortest_dwell": min_d,
			"longest_dwell": max_d,
			"avg_flight": avg_f,
			"sd_flight": sd_f,
			"cv_flight": cv_f,
			"median_flight": med_f,
			"iqr_flight": iqr_f,
			"shortest_flight": min_f,
			"longest_flight": max_f,
			"pause_rate": pause_rate,
			"avg_pause": avg_pause,
			"max_pause": max_pause,
			"avg_burst": avg_burst,
			"max_burst": max_burst,
			"num_bursts": num_burst,
			"backspace_rate": rate(3),
			"correction_burst_max": max_run,
			"total_corrections": total_corr,
			"enter_rate": rate(4),
			"shift_rate": rate(5),
			"arrow_rate": rate(8),
			"punct_rate": rate(12),
			"digit_rate": rate(1),
			"space_rate": rate(2),
			"keys_per_min": keys_per_min,
			"gaming": gaming_enabled.is_set(),
		}
		feats = features_v2.compute_window_features(self.events, self.window_start_ns)
		if feats is None:
			return False
		meta = {
			"schema_version": schema.SCHEMA_VERSION,
			"session": self.session_id,
			"boot_id": self.boot_id,
			"wall_start_utc": align.utc_iso_ms(align.wall_ns_for_perf(self.window_start_ns)),
			"ts_ns_start": self.window_start_ns,
			"gaming_flag": gaming_enabled.is_set(),
			"n_keydowns": n_press,
		}
		legacy = {k: row[k] for k in schema.LEGACY_FEATURE_COLS}
		out = schema.make_window_row(meta, legacy, feats)

		self._ff.writerow([out[c] for c in WINDOW_COLUMNS])
		self._ff_file.flush()
		threading.Thread(target=user_send.send, args=(out,), daemon=True).start()
		return True



	def on_press(self, key):
		try:
			self._on_press(key)
		except Exception as e:
			print(f"[on_press] error: {e!r}")
			_log_event(f"[on_press] error: {e!r}")

	def _on_press(self, key):
		now = time.perf_counter_ns()
		prev = self._press_times.get(key)
		if prev is not None and now - prev < 2_000_000_000:
			return  # OS auto-repeat while the key is held, not a new keystroke
		cat = categorize(key)
		self._press_times[key] = now
		flight_void = {5,6,7,8,9}
		if self._last_press_ns is not None and cat not in flight_void:
			self.all_flight.append(now - self._last_press_ns)

		if cat not in flight_void:
			self._last_press_ns = now


		self.events.append(("press", now, cat, -1))
		self._kw.writerow([self.session_id, now, "press", cat, ""])
		self.last_keystroke_ts = time.time()

		if self.total_press % 10 == 0:
			self._kf.flush()
		self.total_press += 1
		self.window_press += 1
		self.flush_windows()


	def on_release(self, key):
		try:
			self._on_release(key)
		except Exception as e:
			print(f"[on_release] error: {e!r}")
			_log_event(f"[on_release] error: {e!r}")

	def _on_release(self, key):
		now = time.perf_counter_ns()
		cat = categorize(key)
		self.total_release += 1

		press_time = self._press_times.pop(key, None)
		dwell_ns = now - press_time if press_time is not None else -1
		self.events.append(("release", now, cat, dwell_ns))
		self.all_dwell.append(dwell_ns)

		self._kw.writerow([self.session_id, now, "release", cat, dwell_ns])
		if self.total_release % 10 == 0:
			self._kf.flush()
		self.window_release += 1

		self.flush_windows()

	def shutdown(self):
		try:
			self._kf.close()
			self._ff_file.close()
		except Exception:
			pass

	def flush_windows(self):
		now = time.perf_counter_ns()
		if now - self.window_start_ns < self.window_sec *1_000_000_000:
			return

		if len(self.all_dwell) < MIN_KEYSTROKES_PER_WINDOW:
			print(f"Window skipped - only {len(self.all_dwell)} keystrokes")
		else:
			if self._write_window_row(now):
				self.active_window_count += 1

		self.window_press = 0
		self.window_release = 0
		self._kf.flush()
		self.events.clear()
		self.all_dwell.clear()
		self.all_flight.clear()
		self.window_start_ns = now

_session_unlocked = False

def _tray_icon_image():
	img = Image.new("RGB",(64,64),color=(0,0,0))
	draw = ImageDraw.Draw(img)
	locked = not _session_unlocked
	active = dnd_enabled.is_set() or gaming_enabled.is_set()
	draw.ellipse([8,8,56,56], fill=(200,40,40) if (locked or active) else (45,125,70))
	return img

def _tray_title():
	if not _session_unlocked:
		return "TypeSense — Locked"
	modes = []
	if dnd_enabled.is_set():
		modes.append("DND")
	if gaming_enabled.is_set():
		modes.append("Gaming")
	return f"TypeSense - {' + '.join(modes)}" if modes else "TypeSense - Running"

MODE_REMINDER_POLL_MS = 30_000
MODE_REMINDER_FIRST_SEC = 2 * 60 * 60
MODE_REMINDER_REPEAT_SEC = 60 * 60

_mode_flags = {"dnd": dnd_enabled, "gaming": gaming_enabled}
_mode_labels = {"dnd": "Do Not Disturb", "gaming": "Gaming Mode"}
_mode_other = {"dnd": "gaming", "gaming": "dnd"}
_mode_next_reminder_at = {"dnd": None, "gaming": None}

def _set_mode(key, enabled):
	# DND and Gaming Mode are mutually exclusive - turning one on turns the
	# other off, rather than letting both suppress surveys at once.
	if enabled:
		other = _mode_other[key]
		if _mode_flags[other].is_set():
			_mode_flags[other].clear()
			_mode_next_reminder_at[other] = None
		_mode_flags[key].set()
		_mode_next_reminder_at[key] = time.time() + MODE_REMINDER_FIRST_SEC
	else:
		_mode_flags[key].clear()
		_mode_next_reminder_at[key] = None
	if sys.platform != "darwin":
		tray_icon.icon = _tray_icon_image()
		tray_icon.title = _tray_title()

def _mode_reminder_poll():
	now = time.time()
	for key in _mode_flags:
		if not _mode_flags[key].is_set():
			continue
		due_at = _mode_next_reminder_at[key]
		if due_at is None or now < due_at:
			continue
		_mode_next_reminder_at[key] = None  # don't re-fire while the dialog is open
		def _on_stop(key=key):
			_set_mode(key, False)
		def _on_ignore(key=key):
			_mode_next_reminder_at[key] = time.time() + MODE_REMINDER_REPEAT_SEC
		show_mode_reminder(_mode_labels[key], _on_stop, _on_ignore)
	root.after(MODE_REMINDER_POLL_MS, _mode_reminder_poll)

def _confirm_passcode_from_tray(icon, item):
	def _do():
		global _session_unlocked
		for attempt in range(3):
			prompt = (
				"Enter passcode:"
				if attempt == 0
				else f"Wrong passcode. Try again ({attempt + 1}/3):"
			)
			val = simpledialog.askstring("TypeSense — Confirm Passcode", prompt, show="*")
			if val is None:
				return  # cancelled — stay locked
			local_ok = _participant_passcode is not None and val == _participant_passcode
			ok = local_ok
			if not local_ok and val:
				ok = user_send.verify_token(val)
				if ok is None:
					messagebox.showerror("TypeSense", "Can't reach the server. Check your connection and try again.")
					return
			if ok:
				_session_unlocked = True
				user_send.unlock_sending(None if local_ok else val)
				icon.icon = _tray_icon_image()
				icon.title = _tray_title()
				return
		messagebox.showerror("TypeSense", "Too many incorrect attempts.")
	root.after(0, _do)


def tray_icon():
	def quit_app(icon,item):
		icon.stop()
		logger.shutdown()
		os._exit(0)
	def show_survey_now(icon,item):
		def _trigger():
			global _next_survey_at, _interval_start_active_windows
			show_survey(logger.session_id, logger.boot_id)
			_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
			_interval_start_active_windows = logger.active_window_count
		root.after(0, _trigger)
	def show_id_now(icon,item):
		root.after(0, show_session_id)
	def open_raw_folder(icon,item):
		try:
			path = get_app_data_dir() / "simple_data"
			path.mkdir(parents=True, exist_ok=True)
			if sys.platform == "darwin":
				subprocess.Popen(["open", str(path)])
			else:
				os.startfile(str(path))
		except Exception as e:
			_log_event(f"[open_raw_folder] error: {e!r}")
	def show_version_now(icon,item):
		root.after(0, show_app_version)
	def toggle_dnd(icon,item):
		_set_mode("dnd", not dnd_enabled.is_set())
	def toggle_gaming(icon,item):
		_set_mode("gaming", not gaming_enabled.is_set())

	menu = pystray.Menu(
		pystray.MenuItem("Confirm Password", _confirm_passcode_from_tray,
		                 visible=lambda item: not _session_unlocked),
		pystray.MenuItem("Show ID", show_id_now,
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Show Version", show_version_now,
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Show Survey Now", show_survey_now,
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Do Not Disturb", toggle_dnd,
		                 checked=lambda item: dnd_enabled.is_set(),
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Gaming Mode", toggle_gaming,
		                 checked=lambda item: gaming_enabled.is_set(),
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Open Raw Data Folder", open_raw_folder,
		                 visible=lambda item: _session_unlocked),
		pystray.MenuItem("Quit Logger", quit_app),
	)
	icon = pystray.Icon("TypeSense", _tray_icon_image(), _tray_title(), menu)
	return icon

root = tk.Tk()
root.withdraw()
root.attributes("-alpha", 0)
if sys.platform != "darwin":
	root.attributes("-toolwindow", True)

try:
	ensure_autostart()
	ensure_relaunch_task()
	logger = Simplekeylog(window_sec = 15)

	user_send.init_queue(logger.session_id)
	user_send._flush_queue()
	user_send.start_retry_loop()
except Exception as e:
	error_log = get_app_data_dir() / "startup_error.log"
	error_log.write_text(f"{time.ctime()}: {e!r}\n", encoding="utf-8")
	messagebox.showerror(
		"TypeSense failed to start",
		f"TypeSense could not start:\n\n{e}\n\nDetails saved to:\n{error_log}")
	os._exit(1)

if sys.platform != "darwin":
	tray_icon = tray_icon()
	threading.Thread(target=tray_icon.run, daemon=True).start()

SURVEY_POLL_MS = 30_000
# Gates the popup on genuine engagement: enough active windows in the interval
# (not just a stray keystroke) and a keystroke recent enough that they're not AFK.
SURVEY_MIN_ACTIVE_WINDOWS = 4
SURVEY_RECENCY_SEC = 300

_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
_last_poll_at = time.time()
_interval_start_active_windows = logger.active_window_count

def _should_show_survey(now):
	if not _session_unlocked:
		return False
	if dnd_enabled.is_set() or gaming_enabled.is_set():
		return False
	active_windows = logger.active_window_count - _interval_start_active_windows
	if active_windows < SURVEY_MIN_ACTIVE_WINDOWS:
		return False
	if logger.last_keystroke_ts is None or now - logger.last_keystroke_ts > SURVEY_RECENCY_SEC:
		return False
	return True

def survey_poll():
	"""Tk's after() schedules against wall-clock deadlines, but the event loop
	freezes for the duration of a sleep/hibernate - on wake it sees the
	20-minute deadline as already elapsed and would fire the survey instantly.
	Polling frequently and checking the gap since our last poll lets us tell
	"20 minutes really passed" apart from "the machine was asleep", so we
	reset the deadline instead of firing right when the user wakes it up."""
	global _next_survey_at, _last_poll_at, _interval_start_active_windows
	now = time.time()
	gap = now - _last_poll_at
	_last_poll_at = now
	if gap > (SURVEY_POLL_MS / 1000) * 3:
		_next_survey_at = now + SURVEY_INTERVAL_SEC
		_interval_start_active_windows = logger.active_window_count
	elif now >= _next_survey_at:
		if _should_show_survey(now):
			show_survey(logger.session_id, logger.boot_id)
		_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
		_interval_start_active_windows = logger.active_window_count
	root.after(SURVEY_POLL_MS, survey_poll)

def show_app_version():
	root.deiconify()
	root.focus_force()
	messagebox.showinfo("TypeSense Version", "TypeSense")

def show_session_id():
	root.deiconify()
	root.focus_force()
	messagebox.showinfo(
		"Your Participant ID",
		f"Your ID is: {logger.session_id}\n\nPlease send this to Lucas.")

if logger.is_first_run:
	root.after(1000, show_session_id)

root.after(SURVEY_POLL_MS, survey_poll)
root.after(MODE_REMINDER_POLL_MS, _mode_reminder_poll)
def start_listener():
	if sys.platform == "darwin" and not _check_macos_accessibility_permission():
		os._exit(1)
	while True:
		try:
			with Listener(on_press=logger.on_press, on_release=logger.on_release) as listener:
				listener.join()
		except Exception as e:
			print(f"[Listener] crashed: {e!r}, restarting")
			_log_event(f"[Listener] crashed: {e!r}, restarting")
			time.sleep(2)
			continue
		break
threading.Thread(target=start_listener, daemon=True).start()
print("[Logger] Running. Survey every 20m. Use tray icon 'Quit Logger' to stop.")
root.mainloop()
import csv, time, uuid
from pathlib import Path
from pynput.keyboard import Key, Listener
import user_send
import tkinter as tk
from survey import show_survey, SURVEY_INTERVAL_SEC, show_mode_reminder
import threading
import os
import sys
import winreg
import ctypes
import subprocess
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
from app_paths import get_app_data_dir
import updater


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
	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	mutex = kernel32.CreateMutexW(None, False, name)
	if not mutex:
		# CreateMutexW failed outright (not "already exists") - we can't guarantee
		# single-instance, but exiting here would be worse than just logging and continuing.
		_log_event(f"[_create_mutex] CreateMutexW failed, error={ctypes.get_last_error()}")
	elif ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
		os._exit(0)
	return mutex


_single_instance_mutex = _create_mutex("Global\\TypeSenseLogger_SingleInstance_Mutex")


def ensure_autostart():
	if not getattr(sys, "frozen", False):
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

class Simplekeylog:
	def __init__(self, out_dir = None, window_sec = 15):
		self.session_id = self._load_or_create_session_id()
		self.out_dir = Path(out_dir) if out_dir else (get_app_data_dir() / "simple_data")
		self.out_dir.mkdir(parents=True, exist_ok=True)

		self.log_file = self.out_dir / f"keyrecsimp_{self.session_id}.csv"
		self.window_file = self.out_dir / f"importantsimp_{self.session_id}.csv"

		kf_is_new = not self.log_file.exists()
		ff_is_new = not self.window_file.exists()

		self._kf = open(self.log_file, "a", newline='', encoding="utf-8")
		self._ff_file = open(self.window_file, "a", newline='', encoding="utf-8")

		self._ff = csv.writer(self._ff_file)
		self._kw = csv.writer(self._kf)

		if kf_is_new:
			self._kw.writerow(["session","ts_ns","event", "cat", "dwell_time"])
		if ff_is_new:
			self._ff.writerow(["session","time_now", "total_press", "total_release", "avg_dwell", "shortest_dwell", "longest_dwell",
							   "avg_flight", "shortest_flight", "longest_flight", "avg_burst","max_burst","num_bursts","gaming"])

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

	def _write_window_row(self, now):

		avg_d, min_d, max_d = self._jarvis(self.all_dwell)
		avg_f, min_f, max_f = self._jarvis(self.all_flight)
		burst_lens = self._compute_burst()
		avg_burst = round(sum(burst_lens) / len(burst_lens), 2)
		max_burst = max(burst_lens)
		num_burst = len(burst_lens)


		row = {
			"session": self.session_id,
			"time_now": now,
			"total_press": self.total_press,
			"total_release": self.total_release,
			"avg_dwell": avg_d,
			"shortest_dwell": min_d,
			"longest_dwell": max_d,
			"avg_flight": avg_f,
			"shortest_flight": min_f,
			"longest_flight": max_f,
			"avg_burst": avg_burst,
			"max_burst": max_burst,
			"num_bursts": num_burst,
			"gaming": gaming_enabled.is_set(),
		}

		self._ff.writerow(list(row.values()))
		self._ff_file.flush()
		threading.Thread(target=user_send.send, args=(row,), daemon=True).start()



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


		self.events.append(("press", now, cat))
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
		self.events.append(("release", now, cat))
		self.total_release += 1

		press_time = self._press_times.pop(key, None)
		dwell_ns = now - press_time if press_time is not None else -1
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
			self._write_window_row(now)
			self.active_window_count += 1

		self.window_press = 0
		self.window_release = 0
		self._kf.flush()
		self.events.clear()
		self.all_dwell.clear()
		self.all_flight.clear()
		self.window_start_ns = now

def _tray_icon_image():
	img = Image.new("RGB",(64,64),color=(0,0,0))
	draw = ImageDraw.Draw(img)
	active = dnd_enabled.is_set() or gaming_enabled.is_set()
	draw.ellipse([8,8,56,56],fill = (200,40,40) if active else (45,125,70))
	return img

def _tray_title():
	modes = []
	if dnd_enabled.is_set():
		modes.append("DND")
	if gaming_enabled.is_set():
		modes.append("Gaming")
	return f"TypeSense - {' + '.join(modes)}" if modes else "TypeSense - Running"

MODE_REMINDER_POLL_MS = 30_000
MODE_REMINDER_FIRST_SEC = 2 * 60 * 60  # nag once a mode's been on this long
MODE_REMINDER_REPEAT_SEC = 60 * 60     # then keep nagging hourly if ignored

_mode_flags = {"dnd": dnd_enabled, "gaming": gaming_enabled}
_mode_labels = {"dnd": "Do Not Disturb", "gaming": "Gaming Mode"}
# None means "not running" / "no reminder pending" - set to a deadline whenever
# the mode turns on, and cleared whenever it turns off (by any path: tray
# toggle, restart, or the reminder's own Stop button).
_mode_next_reminder_at = {"dnd": None, "gaming": None}

def _set_mode(key, enabled):
	if enabled:
		_mode_flags[key].set()
		_mode_next_reminder_at[key] = time.time() + MODE_REMINDER_FIRST_SEC
	else:
		_mode_flags[key].clear()
		_mode_next_reminder_at[key] = None
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

def tray_icon():
	def quit_app(icon,item):
		icon.stop()
		logger.shutdown()
		os._exit(0)
	def show_survey_now(icon,item):
		def _trigger():
			global _next_survey_at, _interval_start_active_windows
			show_survey(logger.session_id)
			_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
			_interval_start_active_windows = logger.active_window_count
		root.after(0, _trigger)
	def show_id_now(icon,item):
		root.after(0, show_session_id)
	def show_version_now(icon,item):
		root.after(0, show_app_version)
	def toggle_dnd(icon,item):
		# Pauses surveys until toggled back off or the app restarts - it's an
		# in-memory flag, so a restart clears it naturally. Doesn't affect the
		# `gaming` CSV tag - that's Gaming Mode's job.
		_set_mode("dnd", not dnd_enabled.is_set())
	def toggle_gaming(icon,item):
		# Suppresses surveys like DND, but also tags logged windows with
		# gaming=True so training can exclude gaming-session typing patterns.
		_set_mode("gaming", not gaming_enabled.is_set())

	menu = pystray.Menu(
		pystray.MenuItem("Show ID", show_id_now),
		pystray.MenuItem("Show Version", show_version_now),
		pystray.MenuItem("Show Survey Now", show_survey_now),
		pystray.MenuItem("Do Not Disturb", toggle_dnd, checked=lambda item: dnd_enabled.is_set()),
		pystray.MenuItem("Gaming Mode", toggle_gaming, checked=lambda item: gaming_enabled.is_set()),
		pystray.MenuItem("Quit Logger", quit_app)
	)
	icon = pystray.Icon(
		"TypeSenseLogger", _tray_icon_image(),
		"TypeSense - Running",
		menu
	)
	return icon

root = tk.Tk()
root.withdraw()
root.attributes("-alpha", 0)
root.attributes("-toolwindow", True)

try:
	ensure_autostart()
	ensure_relaunch_task()
	logger = Simplekeylog(window_sec = 15)

	user_send.init_queue(logger.session_id)
	user_send._flush_queue()
	user_send.start_retry_loop()
	updater.check_for_update_async()
except Exception as e:
	error_log = get_app_data_dir() / "startup_error.log"
	error_log.write_text(f"{time.ctime()}: {e!r}\n", encoding="utf-8")
	messagebox.showerror(
		"TypeSense failed to start",
		f"TypeSense could not start:\n\n{e}\n\nDetails saved to:\n{error_log}")
	os._exit(1)

tray_icon = tray_icon()
threading.Thread(target=tray_icon.run, daemon=True).start()

SURVEY_POLL_MS = 30_000
SURVEY_MIN_ACTIVE_WINDOWS = 4  # need real activity in at least this many of the ~80 15s windows in the interval
SURVEY_RECENCY_SEC = 300  # skip the survey if the last keystroke was this long ago - they're AFK, don't interrupt

_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
_last_poll_at = time.time()
_interval_start_active_windows = logger.active_window_count

def _should_show_survey(now):
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
			show_survey(logger.session_id)
		_next_survey_at = time.time() + SURVEY_INTERVAL_SEC
		_interval_start_active_windows = logger.active_window_count
	root.after(SURVEY_POLL_MS, survey_poll)

def show_app_version():
	root.deiconify()
	root.focus_force()
	messagebox.showinfo(
		"TypeSense Version",
		f"You are running version: {updater.current_version()}")

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
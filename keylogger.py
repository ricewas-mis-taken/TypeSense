import csv, time, uuid
from pathlib import Path
from pynput.keyboard import Key, Listener
import user_send
import tkinter as tk
from survey import show_survey
import threading
import os
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw




def categorize(key):
	try:
		char = key.char
		if char and char.isalpha(): return 0
		if char and char.isdigit(): return 1
		return 12 #for  punctuation
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
		return 11 #other stuff

class Simplekeylog:
	def __init__(self, out_dir = "simple_data", window_sec = 15):
		self.session_id = str(uuid.uuid4())[:8]
		self.out_dir = Path(out_dir)
		self.out_dir.mkdir(exist_ok=True)

		self.log_file = self.out_dir / f"keyrecsimp_{self.session_id}.csv"
		self.window_file = self.out_dir / f"importantsimp_{self.session_id}.csv"

		self._kf = open(self.log_file, "w", newline='', encoding="utf-8")
		self._ff_file = open(self.window_file, "w", newline='', encoding="utf-8")

		self._ff = csv.writer(self._ff_file)
		self._kw = csv.writer(self._kf)

		self._kw.writerow(["session","ts_ns","event", "cat", "dwell time"])
		self._ff.writerow(["session","time now", "total press", "total release", "avg_dwell", "shortest dwell", "longest dwell",
						   "avg_flight", "shortest flight", "longest flight", "avg_burst","max_burst","num_bursts"])

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

	#helper for computing data

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
		}

		self._ff.writerow(list(row.values()))
		self._ff_file.flush()
		threading.Thread(target=user_send.send, args=(row,), daemon=True).start()



	def on_press(self, key):
		now = time.perf_counter_ns()
		cat = categorize(key)
		self._press_times[cat] = now
		#only track actual keys
		flight_void = {5,6,7,8,9}
		if self._last_press_ns is not None and cat not in flight_void:
			self.all_flight.append(now - self._last_press_ns)

		if cat not in flight_void:
			self._last_press_ns = now


		self.events.append(("press", now, cat))
		self._kw.writerow([self.session_id, now, "press", cat, ""])

		if self.total_press % 10 == 0:
			self._kf.flush()
		self.total_press += 1
		self.window_press += 1
		self.flush_windows()


	def on_release(self, key):
		now = time.perf_counter_ns()
		cat = categorize(key)
		self.events.append(("release", now, cat))
		self.total_release += 1

		press_time = self._press_times.pop(cat, None)
		dwell_ns = now - press_time if press_time is not None else -1
		self.all_dwell.append(dwell_ns)

		self._kw.writerow([self.session_id, now, "release", cat, dwell_ns])
		if self.total_press % 10 == 0:
			self._kf.flush()
		self.window_release += 1
		if key == Key.esc:
			print("Esc detected - Shutting Down")
			try:
				self._kf.close()
				self._ff_file.close()
			except:
				pass

			os._exit(0)

		self.flush_windows()

	def flush_windows(self):
		now = time.perf_counter_ns()
		if now - self.window_start_ns < self.window_sec *1_000_000_000:
			return
		self.window_press=0
		self.window_release = 0
		self._write_window_row(now)
		self._kf.flush()
		self.events.clear()
		self.all_dwell.clear()
		self.all_flight.clear()
		self.window_start_ns = now
		print("Windows reset")

#icon to close program

def tray_icon():
	img = Image.new("RGB",(64,64),color=(0,0,0))
	draw = ImageDraw.Draw(img)
	draw.ellipse([8,8,56,56],fill = (45,125,70))

	def quit_app(icon,item):
		icon.stop()
		os._exit(0)
	def show_survey_now(icon,item):
		root.after(0,lambda:show_survey(logger.session_id))

	menu = pystray.Menu(
		pystray.MenuItem("Show Survey Now", show_survey_now),
		pystray.MenuItem("Quit Logger", quit_app)
	)
	icon = pystray.Icon(
		"KeystrokeLogger", img,
		"KeystrokeLogger - Running",
		menu
	)
	return icon

root = tk.Tk()
root.withdraw()
root.attributes("-alpha", 0)

logger = Simplekeylog(window_sec = 15)

#offline to online ping
user_send.init_queue(logger.session_id)
user_send._flush_queue()
user_send.start_retry_loop()

tray_icon = tray_icon()
threading.Thread(target=tray_icon.run, daemon=True).start()

def survey_scheduler():
	show_survey(logger.session_id)
	root.after(1200000,survey_scheduler)
#for recording name
def show_session_id():

   root.deiconify()
   root.focus_force()
   messagebox.showinfo(
        "Your Participant ID",
        f"Your ID is: {logger.session_id}\n\nPlease send this to Lucas.")

root.after(1000, show_session_id)

root.after(1200000, survey_scheduler)
def start_listener():
	with Listener(on_press=logger.on_press, on_release=logger.on_release) as listener:
		listener.join()
threading.Thread(target=start_listener, daemon=True).start()
print("[Logger] Running. Survey every 20m. ESC to stop.")
root.mainloop()


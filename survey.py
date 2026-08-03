import tkinter as tk
from tkinter import ttk
import time
import winsound
import user_send as sender


SURVEY_INTERVAL_SEC = 1200

def show_survey(session_id: str):
	result = {}
	root = tk.Toplevel()
	root.title("Quick Check in")
	width, height = 320, 420
	x = (root.winfo_screenwidth() - width) // 2
	y = (root.winfo_screenheight() - height) // 2
	root.geometry(f"{width}x{height}+{x}+{y}")
	root.resizable(False, False)
	root.attributes("-topmost", True)
	# -toolwindow hides the minimize/maximize buttons, but Win+Down and the
	# system menu can still minimize the window - snap it back open the
	# instant that happens so it truly can't be minimized away.
	root.attributes("-toolwindow", True)

	def _block_minimize(event=None):
		if root.state() == "iconic":
			root.deiconify()
			root.attributes("-topmost", True)

	root.bind("<Unmap>", _block_minimize)

	def _deny_close(event=None):
		winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

	root.protocol("WM_DELETE_WINDOW", _deny_close)
	root.bind("<Escape>", _deny_close)
	root.bind("<Alt-F4>", _deny_close)

	tk.Label(root, text="Quick Check In!", font=("Arial", 13, "bold")).pack(pady=(16,8))
	sliders = {}
	def add_slider(label, key):
		tk.Label(root, text=label, font=("Arial",10)).pack(anchor="w",padx = 20)
		var = tk.IntVar(value = 4)
		tk.Scale(root, from_=1, to=7, orient="horizontal", variable = var, length=280).pack(padx=20)
		sliders[key] = var

	add_slider("Stress (1 = calm, 7 = very stressed)", "stress")
	add_slider("Focus (1 = scattered, 7 = very focused)", "focus")
	add_slider("Energy (1 = exhausted, 7 = fully charged)", "energy")

	tk.Label(root, text="What are you mainly doing?", font=("Arial", 10)).pack(anchor="w", padx=20, pady=(6,0))
	activity_var = tk.StringVar (value="Writing")
	ttk.Combobox(root, textvariable=activity_var, values=["Coding","Gaming", "Browsing","Studying", "Writing"], state="readonly",width=30).pack(padx=20,pady=4)



	def submit():
		result["session"] = session_id
		result["ts_ns"] = time.perf_counter_ns()
		result["stress"] = sliders["stress"].get()
		result["focus"] = sliders["focus"].get()
		result["energy"] = sliders["energy"].get()
		result["activity"] = activity_var.get()
		root.destroy()

	tk.Button(root, text = "Submit", command=submit, bg="#2d7d46", fg="white", font = ("Arial", 11), width=12).pack(pady=12)
	root.wait_window()


	if "stress" in result:
		sender.send_survey(result)
		print(f"[Survey] sent — stress:{result['stress']} focus:{result['focus']} energy:{result['energy']}")
	else:
		print("[Survey] closed without submitting")


def show_mode_reminder(mode_label: str, on_stop, on_ignore):
	"""Nag popup for a mode (DND/Gaming) that's been left on a long time.
	Unlike the survey, this one is allowed to be closed - closing is treated
	the same as Ignore, the least disruptive option, rather than trapping the
	participant in a dialog over something that isn't required data collection."""
	root = tk.Toplevel()
	root.title("TypeSense")
	width, height = 320, 170
	x = (root.winfo_screenwidth() - width) // 2
	y = (root.winfo_screenheight() - height) // 2
	root.geometry(f"{width}x{height}+{x}+{y}")
	root.resizable(False, False)
	root.attributes("-topmost", True)
	root.attributes("-toolwindow", True)

	def _block_minimize(event=None):
		if root.state() == "iconic":
			root.deiconify()
			root.attributes("-topmost", True)

	root.bind("<Unmap>", _block_minimize)

	def _ignore(event=None):
		root.destroy()
		on_ignore()

	def _stop(event=None):
		root.destroy()
		on_stop()

	root.protocol("WM_DELETE_WINDOW", _ignore)
	root.bind("<Escape>", _ignore)
	root.bind("<Alt-F4>", _ignore)

	tk.Label(
		root, text=f"You have been in {mode_label} for more than 2 hours. Stop?",
		font=("Arial", 11), wraplength=280, justify="center",
	).pack(pady=(24, 16), padx=16)

	btn_frame = tk.Frame(root)
	btn_frame.pack(pady=4)
	tk.Button(btn_frame, text="Stop", command=_stop, bg="#2d7d46", fg="white", font=("Arial", 11), width=10).pack(side="left", padx=10)
	tk.Button(btn_frame, text="Ignore", command=_ignore, bg="#b3261e", fg="white", font=("Arial", 11), width=10).pack(side="left", padx=10)

	root.wait_window()


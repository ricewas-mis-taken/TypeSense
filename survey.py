import tkinter as tk
from tkinter import ttk
import time
import user_send as sender


SURVEY_INTERVAL_SEC = 1200

def show_survey(session_id: str):
	result = {}
	root = tk.Toplevel()
	root.title("Quick Check in")
	root.geometry("320x420")
	root.resizable(False, False)
	root.attributes("-topmost", True)

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
	ttk.Combobox(root, textvariable=activity_var, values=["Coding","Gaming", "Browsing","Studying", "Writing", "Other"], state="readonly",width=30).pack(padx=20,pady=4)



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


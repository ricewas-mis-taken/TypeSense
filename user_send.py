import requests
import json
from pathlib import Path
import threading
import time


SERVER_URL = "http://localhost:5000/data"
SECRET_TOKEN = "we-like-video-editing"
QUEUE_FILE = Path(__file__).parent/"queue"/"offline_queue.jsonl"
QUEUE_FILE.parent.mkdir(exist_ok=True)


def _retry_loop():
	while True:
		time.sleep(30)
		print("rtry loop running, queue finish")
		try:
			_flush_queue()
		except Exception as e:
			print(f"retry error:{e}")
def start_retry_loop():
	threading.Thread(target=_retry_loop, daemon = True).start()

def send(data: dict):
	payload = {"token": SECRET_TOKEN, "data": data}
	try:
		_flush_queue()
		r = requests.post(SERVER_URL, json=payload, timeout = 5)
		if r.status_code != 200:
			_queue(payload)
	except requests.exceptions.RequestException:
		_queue(payload)

def _queue(payload):
	with open(QUEUE_FILE, "a") as f:
		f.write(json.dumps(payload) + "\n")

def _flush_queue():
	queue_dir = Path(__file__).parent/"queue"
	print(f"[FLUSH] looking in: {queue_dir.absolute()}")
	if not queue_dir.exists():
		print("[FLUSH] no queue folder found")
		return
	all_files = list(queue_dir.glob("*.jsonl"))
	if not all_files:
		print("[FLUSH] queue is empty")
		return
	print(f"[FLush] found{len(all_files)}queue files")

	for queue_file in all_files:
		lines = queue_file.read_text().strip().splitlines()
		if not lines:
			continue
		print(f"[Flush] sending {len(lines)}items from {queue_file.name}")
		sent = []
		for line in lines:
			try:
				payload = json.loads(line)
				data = payload.get("data",{})
				if "stress"in data:
					url = SERVER_URL.replace("/data","/survey")
				else:
					url = SERVER_URL
				print(f"[FLUSH] senting to {url}")
				r  = requests.post(url, json=payload,timeout=5)
				print(f"[FLUSH] response: {r.status_code}")
				if r.status_code == 200:
					sent.append(line)
			except Exception as e:
				print(f"[FLUSH] error:{e}")
				break
		remaining = [l for l in lines if l not in sent]
		queue_file.write_text("\n".join(remaining))
		if not remaining:
			queue_file.unlink()
			print(f"[FLUSH] {queue_file.name} cleared and deleted")
		else:print(f"[FLUSH] {queue_file.name} items remaining")


def send_survey(data: dict):
	payload = {"token": SECRET_TOKEN, "data": data}
	try:
		r= requests.post(SERVER_URL.replace("/data", "/survey"),json=payload, timeout = 5)
		if r.status_code != 200:
			_queue(payload)
	except requests.exceptions.RequestException:
		_queue(payload)

def init_queue(session_id: str):
	global QUEUE_FILE
	queue_dir = Path(__file__).parent/"queue"
	queue_dir.mkdir(exist_ok=True)
	QUEUE_FILE = queue_dir/f"queue_{session_id}.jsonl"


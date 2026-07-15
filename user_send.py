import requests
import json
from pathlib import Path
import threading
import time
import sys
from app_paths import get_app_data_dir

if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(sys.executable).parent
else:
    CONFIG_DIR = Path(__file__).parent
BASE_DIR = get_app_data_dir()
_config_path = CONFIG_DIR / "config.json"
if _config_path.exists():
    _cfg = json.loads(_config_path.read_text())
    SERVER_URL = _cfg["server_url"]
    SECRET_TOKEN = _cfg["secret_token"]
else:
    SERVER_URL = None
    SECRET_TOKEN = None

QUEUE_FILE = BASE_DIR/"queue"/"offline_queue.jsonl"
QUEUE_FILE.parent.mkdir(exist_ok=True)

_queue_lock = threading.Lock()


def _require_config():
    if SERVER_URL is None:
        raise RuntimeError(f"Missing config.json at {_config_path} — cannot determine server_url/secret_token")


def _retry_loop():
    while True:
        time.sleep(30)
        print("retry loop running, queue flush")
        try:
            _flush_queue()
        except Exception as e:
            print(f"retry error:{e}")


def start_retry_loop():
    threading.Thread(target=_retry_loop, daemon=True).start()


def send(data: dict):
    payload = {"token": SECRET_TOKEN, "data": data}
    try:
        _flush_queue()
        r = requests.post(SERVER_URL, json=payload, timeout=5)
        if r.status_code != 200:
            _queue(payload)
    except requests.exceptions.RequestException:
        _queue(payload)


def _queue(payload):
    with _queue_lock:
        with open(QUEUE_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")


def _flush_queue():
    with _queue_lock:
        queue_dir = BASE_DIR/"queue"
        if not queue_dir.exists():
            return
        all_files = list(queue_dir.glob("*.jsonl"))
        if not all_files:
            print("[FLUSH] queue is empty")
            return
        print(f"[FLUSH] found {len(all_files)} queue files")

        for queue_file in all_files:
            lines = queue_file.read_text().strip().splitlines()
            if not lines:
                continue
            print(f"[FLUSH] sending {len(lines)} items from {queue_file.name}")
            sent = []
            for line in lines:
                try:
                    payload = json.loads(line)
                    data = payload.get("data", {})
                    if "stress" in data:
                        url = SERVER_URL.replace("/data", "/survey")
                    else:
                        url = SERVER_URL
                    r = requests.post(url, json=payload, timeout=5)
                    print(f"[FLUSH] response: {r.status_code}")
                    if r.status_code == 200:
                        sent.append(line)
                except Exception as e:
                    print(f"[FLUSH] error:{e}")
                    break
            remaining = [l for l in lines if l not in sent]
            tmp_file = queue_file.with_suffix(".tmp")
            tmp_file.write_text("\n".join(remaining))
            tmp_file.replace(queue_file)
            if not remaining:
                queue_file.unlink()
                print(f"[FLUSH] {queue_file.name} cleared and deleted")
            else:
                print(f"[FLUSH] {queue_file.name} items remaining")


def send_survey(data: dict):
    payload = {"token": SECRET_TOKEN, "data": data}
    try:
        r = requests.post(SERVER_URL.replace("/data", "/survey"), json=payload, timeout=5)
        if r.status_code != 200:
            _queue(payload)
    except requests.exceptions.RequestException:
        _queue(payload)


def init_queue(session_id: str):
    global QUEUE_FILE
    _require_config()
    queue_dir = BASE_DIR/"queue"
    queue_dir.mkdir(exist_ok=True)
    QUEUE_FILE = queue_dir/f"queue_{session_id}.jsonl"

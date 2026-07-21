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


def _log_event(msg):
    """The packaged exe is built --noconsole, so print() output has nowhere to
    go - without this, retry/flush errors leave no trace to diagnose later."""
    try:
        with open(BASE_DIR / "runtime.log", "a", encoding="utf-8") as f:
            f.write(f"{time.ctime()}: {msg}\n")
    except Exception:
        pass


def _require_config():
    if SERVER_URL is None:
        raise RuntimeError(f"Missing config.json at {_config_path} — cannot determine server_url/secret_token")


def _survey_url():
    """The config only stores one server_url (the /data endpoint) - derive /survey
    from it explicitly rather than assuming callers get it right, and log loudly
    if server_url doesn't have the expected shape instead of silently misrouting."""
    if SERVER_URL and SERVER_URL.endswith("/data"):
        return SERVER_URL[: -len("/data")] + "/survey"
    _log_event(f"[_survey_url] SERVER_URL {SERVER_URL!r} does not end with '/data' — "
               f"falling back to it unchanged for the survey endpoint, this is likely wrong")
    return SERVER_URL


def _retry_loop():
    while True:
        time.sleep(30)
        _log_event("retry loop running, queue flush")
        try:
            _flush_queue()
        except Exception as e:
            _log_event(f"retry error:{e}")


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
            _log_event("[FLUSH] queue is empty")
            return
        _log_event(f"[FLUSH] found {len(all_files)} queue files")

        for queue_file in all_files:
            lines = queue_file.read_text().strip().splitlines()
            if not lines:
                continue
            _log_event(f"[FLUSH] sending {len(lines)} items from {queue_file.name}")
            sent_idx = set()
            for idx, line in enumerate(lines):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as e:
                    # A malformed line can never parse no matter how many times we
                    # retry it - dropping it (instead of breaking the whole flush)
                    # keeps one bad entry from wedging every item behind it forever.
                    _log_event(f"[FLUSH] dropping unparseable line {idx} in {queue_file.name}: {e}")
                    sent_idx.add(idx)
                    continue
                try:
                    data = payload.get("data", {})
                    if "stress" in data:
                        url = _survey_url()
                    else:
                        url = SERVER_URL
                    r = requests.post(url, json=payload, timeout=5)
                    _log_event(f"[FLUSH] response: {r.status_code}")
                    if r.status_code == 200:
                        sent_idx.add(idx)
                except Exception as e:
                    _log_event(f"[FLUSH] error:{e}")
                    break
            remaining = [l for idx, l in enumerate(lines) if idx not in sent_idx]
            tmp_file = queue_file.with_suffix(".tmp")
            tmp_file.write_text("\n".join(remaining))
            tmp_file.replace(queue_file)
            if not remaining:
                queue_file.unlink()
                _log_event(f"[FLUSH] {queue_file.name} cleared and deleted")
            else:
                _log_event(f"[FLUSH] {queue_file.name} items remaining")


def send_survey(data: dict):
    payload = {"token": SECRET_TOKEN, "data": data}
    try:
        r = requests.post(_survey_url(), json=payload, timeout=5)
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

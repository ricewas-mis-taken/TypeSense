from flask import Flask, request, jsonify
from waitress import serve
import csv, json, re, threading
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # a keystroke-window/survey payload is a few hundred bytes; reject anything wildly larger before it's buffered

DATA_DIR = Path("data")

_server_cfg_path = Path("server_config.json")
if _server_cfg_path.exists():
    SECRET_TOKEN = json.loads(_server_cfg_path.read_text())["secret_token"]
else:
    raise SystemExit("Missing server_config.json with secret_token")

DATA_DIR.mkdir(exist_ok=True)

SURVEY_DIR = Path("surveys")
SURVEY_DIR.mkdir(exist_ok=True)

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_csv_write_lock = threading.Lock()


def _sanitize_cell(value):
    """Neutralize CSV/Excel formula injection - a cell starting with =, +, -, or @
    is interpreted as a formula by Excel/Sheets when the CSV is opened there."""
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value

COLUMNS = [
    "session", "time_now", "total_press", "total_release",
    "avg_dwell", "shortest_dwell", "longest_dwell",
    "avg_flight", "shortest_flight", "longest_flight",
    "avg_burst", "max_burst", "num_bursts",
    "received_at"
]

SURVEY_COLUMNS = ["session", "ts_ns", "stress", "focus",
                  "energy", "activity", "received_at"]


@app.route("/data", methods=["POST"])
def receive_data():
    body = request.get_json()
    if not body or body.get("token") != SECRET_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = body.get("data")
    if not isinstance(data, dict):
        return jsonify({"error": "invalid data"}), 400
    session_id = str(data.get("session", "unknown"))
    if not SESSION_ID_RE.match(session_id):
        return jsonify({"error": "invalid session id"}), 400
    csv_path = DATA_DIR / f"{session_id}.csv"

    data["received_at"] = datetime.now().isoformat()
    row = {k: _sanitize_cell(v) for k, v in data.items()}

    with _csv_write_lock:
        write_header = not csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {session_id}")
    return jsonify({"status": "ok"}), 200


@app.route("/survey", methods=["POST"])
def receive_survey():
    body = request.get_json()
    if not body or body.get("token") != SECRET_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = body.get("data")
    if not isinstance(data, dict):
        return jsonify({"error": "invalid data"}), 400
    session_id = str(data.get("session", "unknown"))
    if not SESSION_ID_RE.match(session_id):
        return jsonify({"error": "invalid session id"}), 400
    csv_path = SURVEY_DIR / f"{session_id}.csv"

    data["received_at"] = datetime.now().isoformat()
    row = {k: _sanitize_cell(v) for k, v in data.items()}

    with _csv_write_lock:
        write_header = not csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SURVEY_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    print(f"[SURVEY] {session_id} - stress:{data.get('stress')} "
          f"focus:{data.get('focus')} energy:{data.get('energy')}")
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=5000)
from flask import Flask, request, jsonify
import csv
from pathlib import Path
from datetime import datetime

app          = Flask(__name__)
DATA_DIR     = Path("data")
SECRET_TOKEN = "we-like-video-editing"
DATA_DIR.mkdir(exist_ok=True)

SURVEY_DIR = Path("surveys")
SURVEY_DIR.mkdir(exist_ok=True)

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

    data       = body["data"]
    session_id = data.get("session", "unknown")
    csv_path   = DATA_DIR / f"{session_id}.csv"

    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        data["received_at"] = datetime.now().isoformat()
        writer.writerow(data)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {session_id}")
    return jsonify({"status": "ok"}), 200


# decorator immediately followed by its function — nothing in between
@app.route("/survey", methods=["POST"])
def receive_survey():
    body = request.get_json()
    if not body or body.get("token") != SECRET_TOKEN:
        return jsonify({"error": "unauthorizedboi"}), 401

    data       = body["data"]
    session_id = data.get("session", "unknown")
    csv_path   = SURVEY_DIR / f"{session_id}.csv"

    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SURVEY_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        data["received_at"] = datetime.now().isoformat()
        writer.writerow(data)

    print(f"[SURVEY] {session_id} — stress:{data.get('stress')} "
          f"focus:{data.get('focus')} energy:{data.get('energy')}")
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
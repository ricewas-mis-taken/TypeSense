from flask import Flask, request, jsonify
from waitress import serve
import csv, json, re, threading
from pathlib import Path
from datetime import datetime
import schema  # shared column lists (also needs features_v2.py next to it)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # a keystroke-window/survey payload is a few hundred bytes; reject anything wildly larger before it's buffered

DATA_DIR = Path("data_v2")            # schema 2.x window rows (with header)
LEGACY_DIR = Path("data_legacy")      # schema 1.x window rows (old logger / old queue)

_server_cfg_path = Path("server_config.json")
if _server_cfg_path.exists():
    SECRET_TOKEN = json.loads(_server_cfg_path.read_text())["secret_token"]
else:
    raise SystemExit("Missing server_config.json with secret_token")

DATA_DIR.mkdir(exist_ok=True)
LEGACY_DIR.mkdir(exist_ok=True)

# New dir: survey rows gained boot_id / wall_start_utc, so they can't share files with old ones.
SURVEY_DIR = Path("surveys_v2")
SURVEY_DIR.mkdir(exist_ok=True)

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_csv_write_lock = threading.Lock()


def _sanitize_cell(value):
    """Neutralize CSV/Excel formula injection - a cell starting with =, +, -, or @
    is interpreted as a formula by Excel/Sheets when the CSV is opened there."""
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value

COLUMNS = schema.SERVER_WINDOW_COLUMNS
LEGACY_COLUMNS = schema.V1_SERVER_COLUMNS
SURVEY_COLUMNS = schema.SURVEY_SERVER_COLUMNS


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_v2(data):
    """Return an error string, or None if the row is a well-formed v2 window row."""
    if set(data) != set(schema.WINDOW_COLUMNS):
        missing = sorted(set(schema.WINDOW_COLUMNS) - set(data))
        extra = sorted(set(data) - set(schema.WINDOW_COLUMNS))
        return (f"expected {len(schema.WINDOW_COLUMNS)} columns, got {len(data)}; "
                f"missing={missing} unexpected={extra}")
    bad = [c for c in schema.FEATURE_COLS if not _is_number(data[c])]
    if bad:
        return f"non-numeric feature values: {bad}"
    return None


def _validate_v1(data):
    missing = [c for c in schema.V1_WINDOW_FIELDS if c not in data]
    return f"v1 row missing columns: {missing}" if missing else None


def _rotate_if_old_schema(csv_path):
    """Files already on disk from <2.0.0 clients have the old header; appending
    new-schema rows would misalign them, so move them aside to *_v1.csv."""
    if not csv_path.exists():
        return
    with open(csv_path, "r", newline="") as f:
        header = next(csv.reader(f), [])
    if not header or header == COLUMNS:
        return
    target = csv_path.with_name(csv_path.stem + "_v1.csv")
    n = 1
    while target.exists():
        n += 1
        target = csv_path.with_name(f"{csv_path.stem}_v1_{n}.csv")
    csv_path.replace(target)


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
    version = str(data.get("schema_version", "1.x"))  # untagged rows come from the v1 logger
    if version.startswith("2."):
        if version != schema.SCHEMA_VERSION:
            return jsonify({"error": f"unsupported schema_version {version!r}"}), 400
        error, columns, out_dir = _validate_v2(data), COLUMNS, DATA_DIR
    elif version.startswith("1."):
        error, columns, out_dir = _validate_v1(data), LEGACY_COLUMNS, LEGACY_DIR
    else:
        return jsonify({"error": f"unknown schema_version {version!r}"}), 400
    if error:
        return jsonify({"error": error}), 400
    csv_path = out_dir / f"{session_id}.csv"

    data["received_at"] = datetime.now().isoformat()
    row = {k: _sanitize_cell(v) for k, v in data.items()}

    with _csv_write_lock:
        if out_dir == DATA_DIR:
            _rotate_if_old_schema(csv_path)
        write_header = not csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
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
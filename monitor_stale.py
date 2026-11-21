"""Alert when a machine (session) has sent no keystroke windows to the server for 2 days.

Run from a user-session scheduled task (see README). Reads the server's data folders,
shows a Windows popup once per outage, and re-arms when the session sends data again.
"""
import csv, ctypes, json, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIRS = ["data", "data_legacy", "data_v2"]
STATE = ROOT / "monitor_state.json"
LOG = ROOT / "alerts.log"
THRESHOLD = timedelta(days=2)


def last_seen():
    seen = {}
    for d in DATA_DIRS:
        for f in (ROOT / d).glob("*.csv"):
            try:
                with open(f, newline="", encoding="utf-8", errors="ignore") as fh:
                    rows = csv.reader(fh)
                    header = next(rows, [])
                    if "received_at" not in header or "session" not in header:
                        continue
                    i = header.index("received_at")
                    si = header.index("session")  # v2 rows start with schema_version, not session
                    for r in rows:
                        if len(r) > max(i, si) and r[i][:2] == "20":
                            try:
                                t = datetime.fromisoformat(r[i])
                            except ValueError:
                                continue
                            if r[si] not in seen or t > seen[r[si]]:
                                seen[r[si]] = t
            except OSError:
                continue
    return seen


def notify(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, msg, "TypeSense - no data", 0x30)


def main(now=None):
    now = now or datetime.now()
    seen = last_seen()
    stale = {s for s, t in seen.items() if now - t > THRESHOLD}
    first_run = not STATE.exists()
    alerted = set() if first_run else set(json.loads(STATE.read_text()).get("alerted", []))
    alerted &= stale  # a session that sent data again is re-armed
    new = stale - alerted
    if not first_run and new:
        lines = [f"{s}: last data {seen[s]:%Y-%m-%d %H:%M}" for s in sorted(new)]
        notify("No keystrokes received for 2+ days from:\n" + "\n".join(lines))
    STATE.write_text(json.dumps({"alerted": sorted(alerted | new)}))
    return sorted(new) if not first_run else []


if __name__ == "__main__":
    main()

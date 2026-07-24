# NOTE: The app now auto-updates itself in the background (checks every 5 minutes). If you're on v1.1.0 or earlier, download the latest installer once — after that you'll always be current automatically.


# TypeSense
### Passive Desktop Typing Dynamics for Real-Time Mood and Cognitive State Prediction



## DISCLAIMER

**THIS LOGGER CAPTURES ZERO CONTENT.** Every key is mapped to a category number:

```
0 = alpha (a-z)        6 = ctrl
1 = digit (0-9)        7 = alt
2 = space              8 = arrow keys
3 = backspace          9 = function keys
4 = enter             10 = escape
5 = shift             11 = other
                      12 = punctuation
```

The raw log file contains rows like:

```
session, timestamp_ns, event, category, dwell_ns
abc12345, 1712938400000, press, 0, ""
abc12345, 1712938400087, release, 0, 87000000
```

A stolen log file tells you "an alpha key was pressed and held for 87ms." It does not tell you which key. Passwords, messages, and private text are structurally protected.

---

## What This Is

A passive, keystroke dynamics research tool that runs silently in the background while participants type normally. Every 15 seconds it computes behavioral features from typing patterns and sends them to a central server. Every 20 minutes it prompts participants with a short mood survey. The goal: train a machine learning model to predict stress, focus, and energy from typing patterns alone — no survey required after training.

Participants can mark a session as **"DND Gaming, No Survey"** from the tray icon when they're gaming or otherwise don't want to be interrupted — logging continues (rows are tagged `gaming=True`), but mood survey popups are suppressed until it's toggled back off. Suspect/gamed windows are also filtered out automatically during dataset compilation (`data_comp.py`) before training.

This project addresses a genuine gap in the literature. **Every major prior study (BiAffect, DeepMood, dpMood) uses smartphone keyboards.** This is the first longitudinal desktop PC keystroke mental health monitoring system with within-person baseline modeling and real-time EMA survey pairing.

---

## Research Context

### The Problem
Mental health monitoring currently relies on clinical appointments, self-report questionnaires, and retrospective recall — all of which are infrequent, burdensome, and subjective. There is a need for passive, continuous, objective biomarkers that work in everyday life.

### The Insight
How you type reflects how your brain is working. Dwell time (how long you hold each key), flight time (how fast you move between keys), and burst length (how long your continuous typing runs are) all change with stress, fatigue, and cognitive load. These signals are capturable from any keyboard.

### The Gap
Prior work is entirely on smartphones. Desktop keyboards capture a fundamentally different behavioral context — the majority of cognitive work, writing, coding, and professional tasks happen on a PC. Nobody has built a longitudinal, deployable desktop tool that pairs keystroke features with real-time mood labels.

### Potential Applications
* Workplace wellbeing monitoring (passive burnout detection)
* Clinical cognitive decline screening (Alzheimer's, Parkinson's early signals)
* Student focus monitoring for EdTech platforms
* Personal mental health tracking (a "Whoop for the brain")

---

## How It Works

```
Participant types normally on their computer
        ↓
keylogger.py captures timing events (not key content — zero content stored)
        ↓
Every 15 seconds: compute dwell time, flight time, burst length
        ↓
Features sent as JSON to research server via HTTPS
        ↓ (in parallel)
Every 20 minutes: mood survey popup appears
Participant rates stress, focus, energy (1-7 scale)
        ↓
Survey answers sent to server, tagged with same session ID
        ↓
data_comp.py joins keystroke windows + survey labels by timestamp
        ↓
training_ALL.csv → ML model training
```

If the participant loses internet connection, all data is saved locally in an offline queue and automatically sent when the connection is restored — on the next keystroke window flush or on next program startup.

---

## Features Computed (Every 15-Second Window)

| Feature | Description | Why It Matters |
|---|---|---|
| `avg_dwell_ms` | Mean key hold duration | Rises with fatigue and stress |
| `min_dwell_ms` | Shortest key hold | Sensitive to modifier key patterns |
| `max_dwell_ms` | Longest key hold (capped 300ms) | Detects held keys vs normal typing |
| `avg_flight_ms` | Mean time between keypresses | Primary cognitive load signal |
| `min_flight_ms` | Fastest key transition | Motor control baseline |
| `max_flight_ms` | Slowest key transition | Pause detection |
| `avg_burst_len` | Mean continuous typing run length | Drops under cognitive overload |
| `max_burst` | Longest single burst | Flow state indicator |
| `num_bursts` | Number of typing bursts per window | Fragmentation of attention |
| `total_press` | Cumulative keypresses | Session activity level |
| `total_release` | Cumulative key releases | Sync check with press count |
| `gaming` | Whether "DND Gaming, No Survey" was active for this window | Lets training exclude gaming-session typing patterns |

### Key Design Decisions
* **Modifier keys excluded from flight time** — shift, ctrl, alt, arrow, function keys create artificially short flight times (microseconds) and are filtered out
* **Dwell time capped at 300ms** — held keys (backspace held to delete, shift held for capitals) are excluded to prevent skewing averages
* **Burst threshold: 200ms** — gaps longer than 200ms between keypresses mark a burst boundary
* **Minimum keystroke count per window** — windows with too few keystrokes (fewer than 8) are dropped as low-confidence, since sparse windows produce noisy statistics
* **Suspect/gamed windows filtered at compile time** — `data_comp.py`'s `is_suspect_window()` flags windows with implausible numeric patterns (e.g. suspiciously uniform dwell/flight times) so they're excluded from `training_ALL.csv` by default
* **Zero key content stored** — every key maps to one of 12 categories (alpha, digit, space, backspace, etc.). The log file cannot reconstruct what anyone typed even if stolen

---

## System Architecture

```
CLIENT (participant's machine)          SERVER (researcher's machine)
─────────────────────────────          ──────────────────────────────
keylogger.py                           client_typesenseML.py (Flask)
  ├── captures keystrokes              ├── POST /data
  ├── computes 15s windows             │     └── data/[session].csv
  ├── shows 20min survey popup         └── POST /survey
  ├── tray icon (ID / survey / DND)          └── surveys/[session].csv
  ├── updater.py — checks GitHub Releases
  │     every 5 min, silently self-updates
  └── user_send.py
        ├── send()        ──HTTPS──►
        ├── send_survey() ──HTTPS──►
        ├── offline queue (local)
        └── retry loop (30s)
```

### Offline Resilience
* Retry loop attempts flush every 30 seconds while running
* On next startup, queue flushed immediately before new data collection
* Survey responses and keystroke windows queued separately, routed to correct endpoints on retry
* Data loss is structurally impossible as long as the queue file isn't deleted

### Tray Icon
Right-click the tray icon for:
* **Show ID** — the participant's session UUID (also shown automatically on first run)
* **Show Version** — the currently installed app version
* **Show Survey Now** — trigger a mood survey immediately
* **DND Gaming, No Survey** — checkbox toggle; suppresses survey popups (logging keeps running, windows are tagged `gaming=True`) — icon turns red while active, green otherwise
* **Quit Logger**

### Auto-Update
The packaged exe polls GitHub Releases every 5 minutes for a newer version, downloads the installer silently, and relaunches — no participant action required. The installed version is tracked in a small local file (not baked into the exe), so it stays accurate across in-place updates.

---

## File Structure

```
keystroke-research/
├── keylogger.py            # Client — main data collection class, tray icon, entry point
├── survey.py                # Client — EMA popup window (tkinter)
├── user_send.py             # Client — server communication + offline queue
├── updater.py                # Client — background auto-updater (GitHub Releases)
├── app_paths.py               # Client — resolves the per-user app data directory
├── version.py                  # Compiled-in fallback version (superseded post-install by the tracked version file)
├── data_comp.py                 # Offline — joins keystroke windows + surveys, filters suspect windows, builds training_ALL.csv
├── client_typesenseML.py    # Server — Flask app with /data and /survey routes
├── config.json               # Client — server URL, secret token, GitHub token (gitignored, not in repo)
├── build.bat                  # Builds the exe via PyInstaller (dist/TypeSenseLogger/)
├── TypeSenseLogger.iss         # Inno Setup script — builds installer/TypeSenseSetup.exe
├── .gitignore                # Excludes all data files, venv, cache, ML pipeline
└── LICENSE                   # MIT
```


## EMA Survey

Every 20 minutes a popup appears asking:

| Question | Scale |
|---|---|
| How stressed are you right now? | 1 (calm) → 7 (very stressed) |
| How focused are you right now? | 1 (scattered) → 7 (laser focused) |
| How energized are you right now? | 1 (exhausted) → 7 (fully charged) |
| What are you mainly doing? | Coding / Writing / Browsing / Studying / Gaming / Other |

Survey responses are timestamped and matched to the keystroke windows immediately preceding them during dataset construction.

---

## Why Within-Person Matters

Every existing system trains population-level models — comparing your typing to everyone else's. But cognitive load is deeply individual. A tired engineer's keystroke variance might look like a focused artist's baseline. Personal baseline modeling addresses this directly.

---

## Literature Context

This project builds on and extends:

* **BiAffect** (Leow et al., UIC) — smartphone keystroke dynamics for bipolar disorder monitoring. The closest prior work. Desktop is the unexplored extension.
* **DeepMood** (Cao et al., 2018) — deep learning on smartphone keystroke metadata for mood prediction.
* **dpMood** (Huang et al., 2018) — personalized mood prediction from smartphone typing dynamics. Explicitly calls for within-person modeling.
* **nQ Medical / TypeNet** (Acien et al., 2022) — keystroke dynamics as biomarker for mental fatigue during natural typing.
* **JMIR Future Proofing Study** (2023) — associations between smartphone keystroke metadata and mental health symptoms in adolescents.

**The gap all of these share:** smartphone only. No desktop. No within-person baseline model. No real-time EMA pairing with sub-minute keystroke windows.

---

## Ethical Considerations

* Zero key content captured — timing and category only
* Data stored on researcher-controlled server, never third-party cloud
* Participant IDs are random session UUIDs, not names
* Participants can withdraw at any time and request data deletion
* IRB application in preparation (likely Exempt under 45 CFR 46.104(d)(2))

---

## Author

**Lucas Tang** — Independent researcher, San Diego CA
Project started 4.11.2026 | V1 complete 5.25.2026
GitHub: [@ricewas-mis-taken](https://github.com/ricewas-mis-taken)

Implementation assisted by AI tools; research design, study protocol, and analysis choices are the author's own.

---

## License
 License — see LICENSE file. 

---

*This project is in active development. V1 (data collection pipeline) is complete and tested.*

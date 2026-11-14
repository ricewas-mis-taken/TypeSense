import os, sys, json, tempfile, threading, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
tmp = tempfile.mkdtemp()
os.environ["LOCALAPPDATA"] = tmp
SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
import user_send as u
got = []; mode = {"fail": True, "fail_after": None}
class H(BaseHTTPRequestHandler):
    def do_POST(s):
        n = int(s.headers["Content-Length"]); body = json.loads(s.rfile.read(n))
        if mode["fail"] or (mode["fail_after"] is not None and len(got) >= mode["fail_after"]):
            s.send_response(500); s.end_headers(); return
        got.append((s.path, body["data"])); s.send_response(200); s.end_headers()
    def log_message(*a): pass
srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
u.SERVER_URL = f"http://127.0.0.1:{port}/data"; u.SECRET_TOKEN = "t"
u.init_queue("sess1")
qf = u.QUEUE_FILE
def lines(): return qf.read_text().splitlines() if qf.exists() else []
# 1 server failing -> queue
for i in range(5): u.send({"i": i})
u.send_survey({"stress": 1, "focus": 2, "energy": 3})
assert len(lines()) == 6, lines(); print("1 queued 6 OK")
# 2 partial flush: accept 3 then fail
mode.update(fail=False, fail_after=3); u._flush_queue()
print("2 after partial: sent", len(got), "remaining", len(lines()))
assert len(got) == 3 and len(lines()) == 3
# 3 new send while remainder exists (server down) -> must not corrupt
mode.update(fail=True, fail_after=None); u.send({"i": 99})
ls = lines(); print("3 lines now", len(ls))
bad = [l for l in ls if not l.strip().startswith("{") or l.count('"token"') != 1]
assert len(ls) == 4 and not bad, ("CORRUPT", ls)
# 4 malformed line dropped, rest delivered, in order, survey routed
with open(qf, "a") as f: f.write("garbage\n")
mode.update(fail=False); u._flush_queue()
print("4 delivered:", [(p, d) for p, d in got])
assert not qf.exists(), "queue not deleted"
items = [d for p, d in got]
assert [d.get("i") for d in items if "i" in d] == [0,1,2,3,4,99], items
assert any(p == "/survey" for p, d in got) and sum(1 for p,d in got if p=="/survey")==1
# 5 concurrency while down
mode["fail"] = True; got.clear()
ts = [threading.Thread(target=u.send, args=({"c": i},)) for i in range(30)]
[t.start() for t in ts]; [t.join() for t in ts]
assert len(lines()) == 30; mode["fail"] = False; u._flush_queue()
assert sorted(d["c"] for p, d in got) == list(range(30)) and not qf.exists(); print("5 concurrency OK")
# 7 legacy file with no trailing newline must not swallow the next entry
qf.write_text(json.dumps({"token": "t", "data": {"l": 1}}))
mode["fail"] = True; u.send({"l": 2}); assert len(lines()) == 2, lines()
mode["fail"] = False; got.clear(); u._flush_queue()
assert sorted(d["l"] for p, d in got) == [1, 2]; print("7 legacy newline OK")
# 6 server fully down (connection refused) then back
srv.shutdown(); srv.server_close(); got.clear()
for i in range(3): u.send({"d": i})
assert len(lines()) == 3; print("6 conn-refused queued OK")
shutil.rmtree(tmp, ignore_errors=True); print("ALL PASS")

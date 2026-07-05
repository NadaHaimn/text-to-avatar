"""Integration smoke tests — run with: python tests/smoke_test.py"""
import urllib.request, urllib.parse, urllib.error, json, sys

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def ok(name): 
    global PASS; PASS += 1
    print(f"  [PASS] {name}")

def fail(name, reason):
    global FAIL; FAIL += 1
    print(f"  [FAIL] {name}: {reason}")

print("\n=== Smoke Tests ===\n")

# ── Test 1: /health ──────────────────────────────────────────────────────────
print("[1] GET /health")
try:
    r = urllib.request.urlopen(f"{BASE}/health")
    h = json.loads(r.read())
    assert h["status"] == "ok", h
    assert h["available_glosses_count"] > 0, h
    assert "avatar_player_base_url" in h, h
    ok("returns status=ok with gloss count and avatar URL")
except Exception as e:
    fail("health check", e)

# ── Test 2: /translate text ──────────────────────────────────────────────────
print("\n[2] POST /translate (text, no Gemini)")
try:
    body = json.dumps({
        "input_type": "text",
        "content": "أنا أذهب إلى المدرسة",
        "simplify_with_gemini": False,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/translate", data=body,
        headers={"Content-Type": "application/json"}
    )
    res = json.loads(urllib.request.urlopen(req).read())
    assert "request_id" in res,          "missing request_id"
    assert "matched_count" in res,       "missing matched_count"
    assert res["matched_count"] >= 0,    "matched_count negative"
    assert res["avatar_player_url"],     "empty avatar_player_url"
    assert "timings" in res,             "missing timings"
    ok(f"matched_count={res['matched_count']}, url={res['avatar_player_url'][:60]}...")
except Exception as e:
    fail("translate text", e)

# ── Test 3: /translate-stream SSE ────────────────────────────────────────────
print("\n[3] GET /translate-stream (SSE)")
try:
    qs  = urllib.parse.urlencode({"text": "أنا أحب المدرسة", "simplify_with_gemini": "false"})
    req = urllib.request.urlopen(f"{BASE}/translate-stream?{qs}", timeout=30)
    events = []
    for line in req:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            events.append(ev["stage"])
            if ev["stage"] in ("done", "error"):
                break
    assert "done" in events, f"no done event, got: {events}"
    ok(f"SSE stages received: {events}")
except Exception as e:
    fail("SSE stream", e)

# ── Test 4: Invalid YouTube URL rejected ─────────────────────────────────────
print("\n[4] POST /translate — invalid YouTube URL (should 400)")
try:
    body = json.dumps({
        "input_type": "youtube",
        "content": "not-a-youtube-url",
        "simplify_with_gemini": False,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/translate", data=body,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)
    fail("invalid YouTube URL", "expected HTTP 400 but got 200")
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    assert e.code == 400, f"expected 400, got {e.code}"
    assert err.get("error_code") == "INVALID_INPUT", err
    ok(f"error_code=INVALID_INPUT, HTTP {e.code}")
except Exception as e:
    fail("invalid YouTube URL", e)

# ── Test 5: Blank text rejected ───────────────────────────────────────────────
print("\n[5] POST /translate — blank text (should 422)")
try:
    body = json.dumps({
        "input_type": "text",
        "content": "   ",
        "simplify_with_gemini": False,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/translate", data=body,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)
    fail("blank text", "expected HTTP 422 but got 200")
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    assert e.code == 422, f"expected 422, got {e.code}"
    assert err.get("error_code") == "INVALID_INPUT", err
    ok(f"error_code=INVALID_INPUT, HTTP {e.code}")
except Exception as e:
    fail("blank text", e)

# ── Test 6: /available-glosses ───────────────────────────────────────────────
print("\n[6] GET /available-glosses")
try:
    r   = urllib.request.urlopen(f"{BASE}/available-glosses")
    res = json.loads(r.read())
    assert res["count"] > 400, f"expected >400 glosses, got {res['count']}"
    assert isinstance(res["glosses"], list), "glosses not a list"
    ok(f"returned {res['count']} glosses")
except Exception as e:
    fail("available-glosses", e)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}\n")
sys.exit(0 if FAIL == 0 else 1)

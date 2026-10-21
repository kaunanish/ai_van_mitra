#!/usr/bin/env python3
"""
AI Van Mitra - backend server (Flask).

    python app.py          then open http://localhost:5055

Routes
  GET  /               kiosk page (the talking tree)
  GET  /events         Server-Sent Events: hardware events (button, presence) -> browser
  POST /api/ask        recorded question (WAV)  -> STT -> answer pipeline
  POST /api/ask_text   typed question (testing / demo backup) -> answer pipeline
  POST /api/state      browser's current state  -> LED ring colour (via Arduino)
  POST /api/hw         demo only: keyboard simulates the Arduino events
  POST /api/visitor    a visitor session started (for the daily visitor count)
  GET  /api/status     health of every component (shown in the demo panel)
  GET  /api/lines      pre-generated greeting / fallback audio
  GET  /admin          PIN-protected statistics page
"""
import logging
import threading
import time

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for

import config
from core import hardware, llm, logger, rules, stt, tts
from core.retriever import Retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("van_mitra")

app = Flask(__name__, static_folder=str(config.STATIC_DIR), static_url_path="/static",
            template_folder=str(config.BASE_DIR / "admin"))
app.secret_key = "van-mitra-" + config.ADMIN_PIN

retriever = Retriever()
pipeline_lock = threading.Lock()   # one question at a time (it's one kiosk)


# =====================================================================  the answer pipeline
def answer_question(question, source, stt_info=None, stt_ms=0):
    """Steps 2-9 of the live algorithm. Returns the response JSON incl. a full trace for the demo panel."""
    t0 = time.time()
    trace = {"question": question, "source": source, "stt": stt_info, "steps": [], "timings": {"stt_ms": stt_ms}}
    step = lambda name, **kw: trace["steps"].append({"step": name, **kw})  # noqa: E731

    route, answer, chunk_ids, top_score, gate_passed, llm_mode = None, None, [], None, None, None

    # 2. quick rules ---------------------------------------------------------------------
    r = rules.match(question)
    if r:
        step("rules", result=f"matched '{r['rule']}'")
        route, answer = "rule", r["answer"]
    else:
        step("rules", result="no small-talk match")

    # 3. pinned answers ------------------------------------------------------------------
    if route is None:
        t = time.time()
        p = retriever.match_pinned(question)
        if p:
            step("pinned", result="HIT" if p["hit"] else "no match", **p)
            if p["hit"]:
                route, answer, top_score = "pinned", p["answer"], p["score"]
        trace["timings"]["pinned_ms"] = int((time.time() - t) * 1000)

    # 4-5. hybrid search + gate ------------------------------------------------------------
    if route is None:
        t = time.time()
        s = retriever.search(question)
        s.pop("qvec", None)
        trace["timings"]["retrieval_ms"] = int((time.time() - t) * 1000)
        trace["retrieval"] = s
        gate = s["gate"]
        gate_passed = gate["passed"]
        top_score = gate["value"]
        chunk_ids = [x["id"] for x in s["results"]]
        step("search", result=f"{len(s['results'])} passages ({s['mode']})")
        step("gate 1 (relevance)", result="PASSED" if gate_passed else "BLOCKED - LLM not called", **gate)

        # 6-7. LLM + output check ----------------------------------------------------------
        if gate_passed and s["results"]:
            t = time.time()
            out = llm.answer(question, s["results"], retriever.idf())
            trace["timings"]["llm_ms"] = int((time.time() - t) * 1000)
            llm_mode = out["mode"]
            trace["llm"] = {"mode": out["mode"], "raw": out["raw"], "model": config.LLM_MODEL if out["mode"] == "llm" else None,
                            "prompt": out.get("prompt")}
            step("gate 2 (answer check)", result="answer OK" if out["status"] == "answered" else "NOT_FOUND -> fallback",
                 mode=out["mode"])
            if out["status"] == "answered":
                route, answer = "rag", out["answer"]
        if route is None:
            route, answer = "fallback", config.FALLBACK_TEXT

    # 8. TTS ---------------------------------------------------------------------------------
    t = time.time()
    audio_url, tinfo = tts.synth(answer)
    trace["timings"]["tts_ms"] = int((time.time() - t) * 1000)
    trace["tts"] = tinfo
    trace["timings"]["total_ms"] = int((time.time() - t0) * 1000) + stt_ms

    # 9. log ---------------------------------------------------------------------------------
    try:
        logger.log_interaction(source, question, route, answer, chunk_ids, top_score, gate_passed, llm_mode,
                               {**trace["timings"]})
    except Exception as e:  # noqa: BLE001
        log.warning("log failed: %s", e)

    log.info("[%s] %r -> %s (%d ms)", source, question, route, trace["timings"]["total_ms"])
    return {"transcript": question, "answer": answer, "audio_url": audio_url, "status": route, "trace": trace}


def special_reply(kind, stt_info=None, stt_ms=0, source="voice"):
    text = {"too_short": config.TOO_SHORT_TEXT, "error": config.ERROR_TEXT}.get(kind, config.NOT_HEARD_TEXT)
    audio_url, _ = tts.synth(text)
    try:
        logger.log_interaction(source, (stt_info or {}).get("text", ""), "not_heard" if kind != "error" else "error", text,
                               t={"stt_ms": stt_ms, "total_ms": stt_ms})
    except Exception:  # noqa: BLE001
        pass
    return {"transcript": (stt_info or {}).get("text", ""), "answer": text, "audio_url": audio_url, "status": "not_heard",
            "trace": {"stt": stt_info, "steps": [{"step": "speech-to-text", "result": f"rejected: {kind}"}],
                      "timings": {"stt_ms": stt_ms, "total_ms": stt_ms}}}


# =====================================================================  routes
@app.get("/")
def index():
    return send_from_directory(config.STATIC_DIR, "index.html")


@app.post("/api/ask")
def api_ask():
    f = request.files.get("audio")
    data = f.read() if f else request.get_data()
    if not data:
        return jsonify({"error": "no audio"}), 400
    with pipeline_lock:
        try:
            t = time.time()
            info = stt.transcribe(data)
            stt_ms = int((time.time() - t) * 1000)
            if not info["ok"]:
                kind = "too_short" if info["reason"] == "too_short" else ("error" if info["reason"] == "stt_unavailable" else "unclear")
                res = special_reply(kind, info, stt_ms)
                res["trace"]["stt_reason"] = info["reason"]
                return jsonify(res)
            return jsonify(answer_question(info["text"], "voice", info, stt_ms))
        except Exception as e:  # noqa: BLE001
            log.exception("ask failed")
            res = special_reply("error")
            res["trace"]["error"] = str(e)
            return jsonify(res)


@app.post("/api/ask_text")
def api_ask_text():
    q = ((request.get_json(silent=True) or {}).get("text") or "").strip()[:300]
    if not q:
        return jsonify({"error": "empty question"}), 400
    with pipeline_lock:
        try:
            return jsonify(answer_question(q, "text"))
        except Exception as e:  # noqa: BLE001
            log.exception("ask_text failed")
            res = special_reply("error", source="text")
            res["trace"]["error"] = str(e)
            return jsonify(res)


@app.get("/events")
def events():
    q = hardware.bus.subscribe()

    def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except Exception:  # noqa: BLE001  (queue.Empty -> heartbeat keeps the connection alive)
                    yield ": ping\n\n"
        finally:
            hardware.bus.unsubscribe(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/hw")
def api_hw():
    ev = ((request.get_json(silent=True) or {}).get("event") or "").upper()
    if ev not in hardware.VALID_EVENTS:
        return jsonify({"error": "bad event"}), 400
    hardware.bus.publish(ev, "keyboard")
    return jsonify({"ok": True, "clients": hardware.bus.clients()})


@app.post("/api/state")
def api_state():
    st = ((request.get_json(silent=True) or {}).get("state") or "").upper()
    if st not in hardware.VALID_STATES:
        return jsonify({"error": "bad state"}), 400
    hardware.set_state(st)
    return jsonify({"ok": True})


@app.post("/api/visitor")
def api_visitor():
    logger.log_event("visitor")
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    return jsonify({
        "stt": stt.status(), "llm": llm.status(), "tts": tts.status(), "hardware": hardware.status(),
        "knowledge": {"ok": True, "mode": retriever.mode, "chunks": len(retriever.chunks),
                      "files": retriever.meta.get("files", []), "built_at": retriever.meta.get("built_at"),
                      "embed_model": retriever.meta.get("embed_model")},
        "config": {"gate_cosine": config.GATE_COSINE, "gate_keyword": config.GATE_BM25_FALLBACK, "top_k": config.TOP_K},
    })


_lines = {}


@app.get("/api/lines")
def api_lines():
    return jsonify(_lines)


# =====================================================================  admin
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not config.ENABLE_ADMIN:
        return "Not found", 404
    if request.method == "POST":
        if request.form.get("pin") == config.ADMIN_PIN:
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error=True)
    if not session.get("admin"):
        return render_template("login.html", error=False)
    return render_template("admin.html", s=logger.stats(), status=api_status().get_json())


@app.get("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin"))


# =====================================================================  start-up
def background_startup():
    """Slow things happen here so the page is available immediately."""
    tts.init()
    for key, text in (("greeting", config.GREETING_TEXT), ("fallback", config.FALLBACK_TEXT),
                      ("not_heard", config.NOT_HEARD_TEXT)):
        url, _ = tts.synth(text)
        _lines[key] = {"text": text, "audio_url": url}
    stt.load()
    llm.warm_up()
    log.info("Van Mitra is ready.  STT=%s  LLM=%s  TTS=%s  knowledge=%s",
             stt.status()["ok"], llm.status()["ok"], tts.status()["engine"], retriever.mode)


def main():
    logger.init()
    hardware.start()
    threading.Thread(target=background_startup, name="startup", daemon=True).start()
    log.info("Open  http://localhost:%d", config.PORT)
    try:
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT, threads=12, channel_timeout=3600)
    except ImportError:
        app.run(host=config.HOST, port=config.PORT, threaded=True)


if __name__ == "__main__":
    main()

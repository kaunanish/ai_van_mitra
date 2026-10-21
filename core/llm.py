"""
PART B, steps 6-7: the small local language model (via Ollama) writes the answer,
using ONLY the retrieved passages.

Gate 2: the model is told to reply exactly NOT_FOUND when the passages don't contain
the answer; we turn that into the friendly fallback line.

If Ollama is not running, we fall back to 'extractive' mode: pick the 2 sentences from the
retrieved passages that best match the question and speak them as they are. Less fluent, but
still 100% from approved material - so the demo never breaks.
"""
import json
import logging
import re
import threading
import time
import urllib.request

import config
from core.textutil import clean_for_speech, split_sentences, tokenize, trim_sentences

log = logging.getLogger("van_mitra.llm")

_status = {"ok": None, "checked": 0.0, "detail": ""}
_lock = threading.Lock()


def _post(path, payload, timeout):
    req = urllib.request.Request(config.OLLAMA_URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def available(force=False):
    """Is Ollama running with our model pulled? Re-checked at most every 20 s."""
    with _lock:
        if not force and _status["ok"] is not None and time.time() - _status["checked"] < 20:
            return _status["ok"]
        try:
            with urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=2) as r:
                models = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
            want = config.LLM_MODEL if ":" in config.LLM_MODEL else config.LLM_MODEL + ":latest"
            ok = want in models
            _status["detail"] = "ready" if ok else f"model {config.LLM_MODEL} not pulled (have: {', '.join(models) or 'none'})"
        except Exception as e:  # noqa: BLE001
            ok = False
            _status["detail"] = f"Ollama not reachable ({e.__class__.__name__})"
        _status.update(ok=ok, checked=time.time())
        return ok


def status():
    available()
    return {"ok": bool(_status["ok"]), "model": config.LLM_MODEL, "detail": _status["detail"]}


def warm_up():
    """Load the model into memory once at start-up so the first visitor doesn't wait."""
    if not available(force=True):
        log.warning("LLM: %s -> extractive mode", _status["detail"])
        return
    try:
        t = time.time()
        _post("/api/generate", {"model": config.LLM_MODEL, "prompt": "Hello", "keep_alive": config.LLM_KEEP_ALIVE,
                                "options": {"num_predict": 1}}, timeout=120)
        log.info("LLM %s warmed up in %.1fs", config.LLM_MODEL, time.time() - t)
    except Exception as e:  # noqa: BLE001
        log.warning("LLM warm-up failed: %s", e)


def build_prompt(question, passages):
    ctx = "\n\n".join(f"[{i + 1}] {p['section']}\n{p['text']}" for i, p in enumerate(passages))
    return f"CONTEXT:\n{ctx}\n\nQUESTION: {question}\n\nANSWER (or NOT_FOUND):"


def answer(question, passages, idf=None):
    """Returns dict: {status: answered|not_found, answer, raw, mode, prompt}."""
    if available():
        prompt = build_prompt(question, passages)
        try:
            res = _post("/api/chat", {
                "model": config.LLM_MODEL,
                "messages": [{"role": "system", "content": config.SYSTEM_PROMPT},
                             {"role": "user", "content": prompt}],
                "stream": False,
                "keep_alive": config.LLM_KEEP_ALIVE,
                "options": {"temperature": config.LLM_TEMPERATURE, "num_predict": config.LLM_MAX_TOKENS,
                            "num_ctx": 4096},
            }, timeout=config.LLM_TIMEOUT_S)
            raw = res.get("message", {}).get("content", "").strip()
            out = _check(raw, "llm", prompt)
            if out["status"] == "answered":
                wrong = foreign_places(out["answer"], passages)
                if wrong:
                    # the small model swapped in a place it "remembers" (e.g. Haryana for Odisha)
                    log.warning("LLM named %s, not in the passages -> extractive answer instead", wrong)
                    ex = extractive(question, passages, idf or {})
                    ex["raw"] = f"[rejected LLM answer, wrong place {wrong}] {raw}"
                    return ex
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("LLM call failed (%s) -> extractive", e)
            _status.update(ok=False, checked=time.time(), detail=f"call failed: {e.__class__.__name__}")
    return extractive(question, passages, idf or {})


# Gate 3 (place check): a 3B model sometimes slips in a state it "remembers" from training
# (e.g. "Haryana" instead of "Odisha"). Any Indian state / big city in the answer must also
# appear in the retrieved passages, otherwise the answer is thrown away.
PLACE_NAMES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
    "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "punjab", "rajasthan", "sikkim",
    "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", "bengal",
    "delhi", "jammu", "kashmir", "ladakh", "chandigarh", "puducherry", "gurugram", "gurgaon",
    "mumbai", "kolkata", "chennai", "bengaluru", "bangalore", "hyderabad", "jaipur", "lucknow",
    "patna", "ranchi", "raipur", "bhopal", "aravalli", "sundarbans", "nepal", "bangladesh",
]


def foreign_places(answer_text, passages):
    """Places named in the answer that are NOT in the passages (should be empty)."""
    ctx = " ".join(f"{p.get('section', '')} {p.get('text', '')}" for p in passages).lower()
    a = (answer_text or "").lower()
    return [pl for pl in PLACE_NAMES if re.search(r"\b" + re.escape(pl) + r"\b", a) and pl not in ctx]


def _check(raw, mode, prompt=None):
    """Output check: NOT_FOUND -> fallback; strip markdown; at most N sentences."""
    if not raw or "NOT_FOUND" in raw.upper().replace(" ", "_"):
        return {"status": "not_found", "answer": None, "raw": raw, "mode": mode, "prompt": prompt}
    text = trim_sentences(clean_for_speech(raw), config.MAX_ANSWER_SENTENCES)
    if len(text) < 3:
        return {"status": "not_found", "answer": None, "raw": raw, "mode": mode, "prompt": prompt}
    return {"status": "answered", "answer": text, "raw": raw, "mode": mode, "prompt": prompt}


def extractive(question, passages, idf):
    """No-LLM backup: the best-matching sentences, copied word for word from the top passages."""
    q = set(tokenize(question))
    scored = []
    for pi, p in enumerate(passages[:2]):
        sents = split_sentences(p["text"])
        for si, s in enumerate(sents):
            st = set(tokenize(s))
            score = sum(idf.get(w, 1.0) for w in q & st) * (1.0 if pi == 0 else 0.7)
            if score > 0:
                scored.append((score, pi, si, s, sents))
    if not scored:
        return {"status": "not_found", "answer": None, "raw": "", "mode": "extractive", "prompt": None}
    scored.sort(key=lambda x: -x[0])
    _, pi, si, s, sents = scored[0]
    picked = [(si, s)]
    # a sentence starting with "That/This/It..." needs the one before it to make sense
    if si > 0 and s.split()[0].lower().strip(",") in {"that", "this", "these", "it", "they", "so", "unlike", "because", "its", "their"}:
        picked.insert(0, (si - 1, sents[si - 1]))
    elif si + 1 < len(sents) and len(s.split()) < 25:
        nxt = sents[si + 1]
        if nxt.split()[0].lower().strip(",") in {"that", "this", "these", "it", "they", "so", "its", "their", "he", "she"}:
            picked.append((si + 1, nxt))
    text = " ".join(x[1] for x in picked)
    text = re.sub(r"^[A-Z][^:.]{2,60}:\s+", "", text)  # drop an inline section heading
    return {"status": "answered", "answer": text, "raw": text, "mode": "extractive", "prompt": None}

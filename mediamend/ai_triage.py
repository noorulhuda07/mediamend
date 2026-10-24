"""Local vision-language triage via Ollama. Advisory only: it never moves files."""
import base64, io, json, time
import requests
from PIL import Image

DEFAULT_MODEL = "qwen2.5vl:3b"  # confirm the exact tag with `ollama list`
PROMPT_VERSION = "v1"
OLLAMA_URL = "http://localhost:11434/api/chat"
VALUES = {"high", "medium", "low", "uncertain"}
PRIORITIES = {"keep", "review", "likely_discard"}

PROMPT = """You are assisting a content creator with media review.

Technical findings: {findings}

Assess the visible image's possible creative value. Could it plausibly be a useful
reference, candid moment, artistic effect, or other content worth retaining?

Return JSON only:
{{"possible_value": "high|medium|low|uncertain", "reason": "brief explanation",
"review_priority": "keep|review|likely_discard"}}

Do not recommend deletion solely because the image is blurry. If uncertain, choose review."""


def _encode(path):
    img = Image.open(path).convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def assess(record, model=DEFAULT_MODEL, timeout=120):
    base = {"model": model, "prompt_version": PROMPT_VERSION}
    t0 = time.perf_counter()
    fail = lambda status, err: {**base, "status": status, "error": err[:200], "possible_value": "uncertain",
                                "review_priority": "review", "reason": "AI assessment unavailable.",
                                "duration_s": round(time.perf_counter() - t0, 1)}
    try:
        findings = "; ".join(record["reasons"]) or "none"
        r = requests.post(OLLAMA_URL, timeout=timeout, json={
            "model": model, "stream": False, "format": "json",
            "messages": [{"role": "user", "content": PROMPT.format(findings=findings),
                          "images": [_encode(record["path"])]}]})
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except Exception as e:
        return fail("unavailable", f"{type(e).__name__}: {e}")
    if data.get("possible_value") not in VALUES or data.get("review_priority") not in PRIORITIES:
        return fail("invalid_output", f"Unexpected labels: {str(data)[:120]}")
    return {**base, "status": "ok", "possible_value": data["possible_value"],
            "review_priority": data["review_priority"], "reason": str(data.get("reason", ""))[:300],
            "duration_s": round(time.perf_counter() - t0, 1)}

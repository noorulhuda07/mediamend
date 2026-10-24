"""Deterministic detectors: empty files, blur, low resolution, blank video frames, silence, exact duplicates."""
import os, subprocess, time
from collections import defaultdict
from pathlib import Path
import cv2
import numpy as np
from safe_actions import BIN_DIR, ARCHIVE_DIR, MANIFEST, sha256

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}

# These are hypotheses to tune on your benchmark, not validated boundaries.
BLUR_THRESHOLD = 50.0
LOW_RES_PIXELS = 640 * 360  # below 360p; tune on your benchmark
BLANK_FRAME_STD = 5.0
BLANK_SHARE_FLAG = 0.5
SILENCE_RATIO_FLAG = 0.95
SILENCE_ABS_FLOOR = 20.0  # int16 RMS; ~ -64 dBFS


def sharpness(gray):
    h, w = gray.shape[:2]
    scale = 1024 / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyze_image(path, rec):
    img = cv2.imread(str(path))
    if img is None:
        rec["reasons"].append("Unreadable image")
        return
    h, w = img.shape[:2]
    s = sharpness(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    rec["metrics"].update(width=w, height=h, sharpness=round(s, 1))
    if s < BLUR_THRESHOLD:
        rec["reasons"].append(f"Possible blur (sharpness {s:.1f} < {BLUR_THRESHOLD:g})")
    if w * h < LOW_RES_PIXELS:
        rec["reasons"].append(f"Low resolution ({w}x{h})")


def analyze_video(path, rec, samples=5):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        rec["reasons"].append("Unreadable video")
        return
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sharp, blank, read = [], 0, 0
    for idx in np.linspace(0, max(n - 1, 0), samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok:
            continue
        read += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.std() < BLANK_FRAME_STD:
            blank += 1
        sharp.append(sharpness(gray))
    cap.release()
    if read == 0:
        rec["reasons"].append("No frames could be read")
        return
    med = float(np.median(sharp))
    rec["metrics"].update(width=w, height=h, duration_s=round(n / fps, 1) if fps else None,
                          sharpness=round(med, 1), blank_share=round(blank / read, 2), frames_sampled=read)
    if blank / read >= BLANK_SHARE_FLAG:
        rec["reasons"].append(f"{blank}/{read} sampled frames are blank")
    if med < BLUR_THRESHOLD:
        rec["reasons"].append(f"Possible blur in sampled frames (median {med:.1f})")
    if w * h and w * h < LOW_RES_PIXELS:
        rec["reasons"].append(f"Low resolution ({w}x{h})")


def analyze_audio(path, rec):
    try:
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True, timeout=120)
    except FileNotFoundError:
        rec["error"] = "ffmpeg not found; audio not analysed"
        return
    except subprocess.TimeoutExpired:
        rec["error"] = "ffmpeg timed out"
        return
    if out.returncode != 0 or len(out.stdout) < 2:
        rec["reasons"].append("Unreadable or empty audio")
        return
    x = np.frombuffer(out.stdout, dtype=np.int16).astype(np.float64)
    win = 800  # 50 ms
    k = len(x) // win
    if k == 0:
        rec["reasons"].append("Extremely short audio")
        return
    rms = np.sqrt((x[: k * win].reshape(k, win) ** 2).mean(axis=1))
    ref = float(np.percentile(rms, 95))
    silent = rms < max(ref * 0.1, SILENCE_ABS_FLOOR)  # relative to this recording's own level
    ratio = float(silent.mean())
    rec["metrics"].update(duration_s=round(len(x) / 16000, 1), silence_ratio=round(ratio, 2), level_rms=round(ref, 1))
    if ratio >= SILENCE_RATIO_FLAG:
        rec["reasons"].append(f"{ratio:.0%} silent or near-silent (listen before deciding)")


def inspect_file(path):
    p = Path(path)
    ext = p.suffix.lower()
    mtype = "photo" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "other"
    rec = {"path": str(p), "name": p.name, "media_type": mtype, "size_bytes": p.stat().st_size,
           "reasons": [], "metrics": {}, "error": None}
    t0 = time.perf_counter()
    try:
        if rec["size_bytes"] == 0:
            rec["reasons"].append("Zero-byte file")
        elif mtype == "photo":
            analyze_image(p, rec)
        elif mtype == "video":
            analyze_video(p, rec)
        elif mtype == "audio":
            analyze_audio(p, rec)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["scan_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return rec


def scan_folder(root, progress=None):
    root = Path(root)
    skip = {BIN_DIR, ARCHIVE_DIR}
    files = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            fp = Path(dp) / f
            if f != MANIFEST and not f.endswith(".tmp") and not fp.is_symlink():
                files.append(fp)
    results = []
    for i, fp in enumerate(sorted(files), 1):
        results.append(inspect_file(fp))
        if progress:
            progress(i, len(files))
    by_size = defaultdict(list)
    for r in results:
        if r["size_bytes"] > 0:
            by_size[r["size_bytes"]].append(r)
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash = defaultdict(list)
        for r in group:
            by_hash[sha256(r["path"])].append(r)
        for dupes in by_hash.values():
            for r in dupes[1:]:
                r["reasons"].append(f"Exact duplicate of {dupes[0]['name']}")
    for r in results:
        r["status"] = "review" if r["reasons"] else "keep"
    return results

"""Bin / archive / restore / permanent-delete with a checksum manifest."""
import hashlib, json, os, shutil, time, uuid
from pathlib import Path

BIN_DIR = "MediaMend_Bin"
ARCHIVE_DIR = "MediaMend_Archive"
MANIFEST = ".mediamend_manifest.json"


class ActionError(Exception):
    pass


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_manifest(root):
    p = Path(root) / MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_manifest(root, entries):
    p = Path(root) / MANIFEST
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _inside(root, p):
    return Path(p).resolve().is_relative_to(Path(root).resolve())


def _safe_move(src, dst, expected_hash):
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise ActionError(f"Destination already exists, not overwriting: {dst}")
    if os.stat(src).st_dev == os.stat(dst.parent).st_dev:
        os.rename(src, dst)
    else:  # cross-filesystem: copy, verify, then remove source
        shutil.copy2(src, dst)
        if sha256(dst) != expected_hash:
            dst.unlink()
            raise ActionError("Checksum mismatch after copy; source left untouched.")
        src.unlink()
    if sha256(dst) != expected_hash:
        raise ActionError(f"Checksum mismatch after move: {dst}")


def _find(entries, eid):
    for e in entries:
        if e["id"] == eid:
            return e
    raise ActionError("Unknown item.")


def move_to_bin(root, path):
    root = Path(root).resolve()
    src = Path(path)
    if src.is_symlink() or not src.is_file():
        raise ActionError(f"Not an ordinary file: {src}")
    if not _inside(root, src):
        raise ActionError(f"File is outside the scan folder: {src}")
    rel = src.resolve().relative_to(root).parts
    if rel[0] in (BIN_DIR, ARCHIVE_DIR):
        raise ActionError("File is already managed by MediaMend.")
    digest = sha256(src)
    eid = uuid.uuid4().hex[:12]
    dst = root / BIN_DIR / f"{eid}_{src.name}"
    entries = load_manifest(root)
    entry = {"id": eid, "original_path": str(src.resolve()), "current_path": str(dst),
             "size_bytes": src.stat().st_size, "sha256": digest, "status": "pending", "updated": _now()}
    entries.append(entry)
    save_manifest(root, entries)
    try:
        _safe_move(src, dst, digest)
        entry["status"] = "bin"
    except Exception as e:
        entry["status"], entry["error"] = "failed", str(e)
        save_manifest(root, entries)
        raise ActionError(str(e))
    entry["updated"] = _now()
    save_manifest(root, entries)
    return entry


def restore(root, eid):
    entries = load_manifest(root)
    e = _find(entries, eid)
    if e["status"] not in ("bin", "archived"):
        raise ActionError(f"Cannot restore an item with status '{e['status']}'.")
    orig = Path(e["original_path"])
    if orig.exists():
        raise ActionError(f"Original location is occupied, nothing overwritten: {orig}")
    _safe_move(e["current_path"], orig, e["sha256"])
    e.update(status="restored", current_path=str(orig), updated=_now())
    save_manifest(root, entries)
    return e


def archive(root, eid):
    entries = load_manifest(root)
    e = _find(entries, eid)
    if e["status"] != "bin":
        raise ActionError("Only items in the Bin can be archived.")
    dst = Path(root).resolve() / ARCHIVE_DIR / Path(e["current_path"]).name
    _safe_move(e["current_path"], dst, e["sha256"])
    e.update(status="archived", current_path=str(dst), updated=_now())
    save_manifest(root, entries)
    return e


def delete_permanent(root, eid):
    """Irreversible. Only items currently in the Bin can be deleted."""
    entries = load_manifest(root)
    e = _find(entries, eid)
    if e["status"] != "bin":
        raise ActionError("Only items in the Bin can be permanently deleted.")
    cur = Path(e["current_path"])
    if not _inside(Path(root) / BIN_DIR, cur):
        raise ActionError("Refusing to delete a file outside the Bin.")
    cur.unlink()
    e.update(status="deleted", updated=_now())
    save_manifest(root, entries)
    return e

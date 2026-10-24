import os
import time
from pathlib import Path
import pandas as pd
import streamlit as st
import analyzers, ai_triage, safe_actions as sa

DEMO_MODE = os.getenv("MEDIAMEND_DEMO", "").lower() in {"1", "true", "yes"}
DEMO_ROOT = Path(__file__).parent / "demo_media"

st.set_page_config(page_title="MediaMend", layout="wide")
st.title("MediaMend")
if DEMO_MODE:
    st.warning("Public read-only demo: only bundled synthetic media is scanned; file actions and local AI are disabled.")
else:
    st.caption("Everything runs on this computer. Nothing is uploaded. AI suggestions are advisory; you decide.")

ss = st.session_state
ss.setdefault("results", [])
if DEMO_MODE:
    if not DEMO_ROOT.is_dir():
        st.error("Bundled demo media folder is missing.")
        st.stop()
    ss["root"] = str(DEMO_ROOT.resolve())
    st.sidebar.info("Scanning the bundled synthetic test corpus.")
    st.sidebar.caption("Local AI triage is disabled in this public demo.")
    use_ai = False
    model = ai_triage.DEFAULT_MODEL
else:
    root_txt = st.sidebar.text_input("Media folder (use a test folder first)", value=ss.get("root", ""))
    use_ai = st.sidebar.checkbox("Local AI triage for flagged photos (Ollama)")
    model = st.sidebar.text_input("Model", ai_triage.DEFAULT_MODEL)

if st.sidebar.button("Scan", type="primary"):
    root = DEMO_ROOT if DEMO_MODE else Path(root_txt).expanduser()
    if not root.is_dir():
        st.sidebar.error("Folder not found.")
    else:
        bar, t0 = st.progress(0.0), time.perf_counter()
        res = analyzers.scan_folder(root, lambda i, n: bar.progress(i / max(n, 1)))
        if use_ai:
            for r in res:
                if r["media_type"] == "photo" and r["status"] == "review":
                    r["ai"] = ai_triage.assess(r, model)
        ss.update(root=str(root.resolve()), results=res, scan_secs=round(time.perf_counter() - t0, 1))
        bar.empty()

if ss.get("msg"):
    st.success(ss.pop("msg"))
if ss.get("err"):
    st.error(ss.pop("err"))

root = ss.get("root")
if not root:
    st.info("Enter a folder path in the sidebar and press Scan.")
    st.stop()

mb = lambda b: f"{b / 1e6:.1f} MB"
tabs = st.tabs(["Read-only demo review"] if DEMO_MODE else ["Review queue", "MediaMend Bin & Archive"])
tab_review = tabs[0]

with tab_review:
    flagged = [r for r in ss["results"] if r["status"] == "review" and Path(r["path"]).exists()]
    st.write(f"Scanned {len(ss['results'])} files in {ss.get('scan_secs', '?')} s. Flagged: {len(flagged)}.")
    if ss["results"]:
        df = pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("metrics", "reasons", "ai")},
                            "reasons": "; ".join(r["reasons"]), **r["metrics"],
                            "ai_priority": r.get("ai", {}).get("review_priority")} for r in ss["results"]])
        st.download_button("Export scan results (CSV)", df.to_csv(index=False), "mediamend_scan.csv")
    chosen = []
    for i, r in enumerate(flagged):
        ai = r.get("ai")
        c1, c2, c3 = st.columns([1, 5, 1])
        with c1:
            if r["media_type"] == "photo" and "width" in r["metrics"]:
                st.image(r["path"], width=110)
            elif r["media_type"] == "photo":
                st.caption("Preview unavailable: image could not be read.")
        with c2:
            st.markdown(f"**{r['name']}** · {r['media_type']} · {mb(r['size_bytes'])}")
            st.write("; ".join(r["reasons"]))
            if ai:
                st.caption(f"AI ({ai['model']}, {ai['status']}): {ai['possible_value']} value, "
                           f"suggests *{ai['review_priority']}*. {ai['reason']}")
            if r["error"]:
                st.caption(f"Note: {r['error']}")
            if r["media_type"] in ("audio", "video"):
                with st.expander("Preview"):
                    (st.audio if r["media_type"] == "audio" else st.video)(r["path"])
        if DEMO_MODE:
            with c3:
                st.caption("Read only")
        else:
            default = not (ai and ai["review_priority"] == "keep") and r["media_type"] != "audio"
            with c3:
                if st.checkbox("Move to Bin", value=default, key=f"sel_{i}_{r['path']}"):
                    chosen.append(r)
    if DEMO_MODE:
        st.info("This demo is read-only. No files can be moved, restored, archived, or deleted.")
        st.stop()

    tot = sum(r["size_bytes"] for r in chosen)
    st.write(f"**{len(chosen)} selected, {mb(tot)} would leave your folders** (potential space to reclaim once the Bin is emptied).")
    ok = st.checkbox("I understand these files will be moved into the MediaMend Bin (not deleted yet).")
    if st.button("Move selected to Bin", disabled=not (ok and chosen)):
        done, errs = 0, []
        for r in chosen:
            try:
                sa.move_to_bin(root, r["path"]); done += 1
            except sa.ActionError as e:
                errs.append(str(e))
        ss["msg"] = f"Moved {done} file(s) to the Bin."
        if errs:
            ss["err"] = " | ".join(errs)
        st.rerun()

tab_bin = tabs[1]
with tab_bin:
    entries = sa.load_manifest(root)
    in_bin = [e for e in entries if e["status"] == "bin"]
    arch = [e for e in entries if e["status"] == "archived"]
    a, b, c = st.columns(3)
    a.metric("Files in Bin", len(in_bin)); b.metric("Bin size", mb(sum(e["size_bytes"] for e in in_bin)))
    c.metric("Archived", len(arch))

    def act(fn, eid, text):
        try:
            fn(root, eid); ss["msg"] = text
        except sa.ActionError as e:
            ss["err"] = str(e)
        st.rerun()

    st.subheader("Bin")
    for e in in_bin:
        c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1.4, 2])
        c1.write(f"**{Path(e['original_path']).name}** · {mb(e['size_bytes'])}\n\nfrom `{e['original_path']}`")
        if c2.button("Restore", key=f"r_{e['id']}"): act(sa.restore, e["id"], "Restored.")
        if c3.button("Archive", key=f"a_{e['id']}"): act(sa.archive, e["id"], "Archived.")
        sure = c4.checkbox("Confirm delete", key=f"c_{e['id']}")
        if c5.button("Delete permanently", key=f"d_{e['id']}", disabled=not sure):
            act(sa.delete_permanent, e["id"], "Permanently deleted. MediaMend cannot undo this.")
    if in_bin:
        st.warning("Permanent deletion cannot be undone through MediaMend, and may not securely erase "
                   "every physical copy (SSDs, backups, synced folders).")
        word = st.text_input("Type DELETE to empty the whole Bin")
        if st.button("Empty Bin", disabled=word != "DELETE"):
            for e in in_bin:
                try: sa.delete_permanent(root, e["id"])
                except sa.ActionError as ex: ss["err"] = str(ex)
            ss["msg"] = "Bin emptied."; st.rerun()
    st.subheader("Archive")
    for e in arch:
        c1, c2 = st.columns([6, 1])
        c1.write(f"**{Path(e['original_path']).name}** · {mb(e['size_bytes'])} · from `{e['original_path']}`")
        if c2.button("Restore", key=f"ra_{e['id']}"): act(sa.restore, e["id"], "Restored.")

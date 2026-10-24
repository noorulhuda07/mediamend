# MediaMend

Local AI-assisted media triage: finds likely discards (blur, blank video frames, silent audio, zero-byte files, exact duplicates), explains why, and moves files you approve into a recoverable **Bin**. From the Bin you can **Restore**, **Archive**, or **Delete permanently** (separate confirmation).

Everything runs on your computer. Nothing is uploaded.

## Setup (VS Code terminal)
```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell   |   source .venv/bin/activate  (macOS/Linux)
pip install -r requirements.txt
ffmpeg -version                   # install FFmpeg if missing (needed for audio)
streamlit run app.py
```
Optional local AI: install Ollama, then `ollama pull qwen2.5vl:3b` (confirm the tag in the Ollama library) and tick "Local AI triage". If Ollama is not running, the app shows an honest "unavailable" status and still works.

## Tests
`python -m unittest discover tests` (checks move, restore hash, no overwrite, delete rules).

## Public Render demo

The repository's `render.yaml` deploys a read-only demo using the bundled synthetic
media in `demo_media/`. In this mode, MediaMend cannot scan an arbitrary server path,
move files, restore or archive them, permanently delete files, or call local Ollama.
Use the local setup above to work with your own files; a cloud-hosted service cannot
access folders on your computer.

The demo is intended for evaluation only. Render's free service uses ephemeral
storage, so files changed on the service would not persist across restarts or deploys.

## Try it safely
Create a test folder of copies (never your only copy of real footage). Thresholds in `analyzers.py` are hypotheses to tune on your own benchmark.
Bin, Archive and the manifest live inside the scanned folder (`MediaMend_Bin/`, `MediaMend_Archive/`, `.mediamend_manifest.json`).

## Limitations
Blur threshold, silence rules and AI judgments can be wrong. Deleting may not securely erase every physical copy (SSDs, backups, synced storage).

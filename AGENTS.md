# AGENTS.md — Codex Instructions (Windows Video Downloader + UI)

You are assisting me in building a **Windows desktop app** for downloading videos (YouTube/TikTok/etc.) with a **clean UI** and reliable downloads.

## 0) Primary goals
Build a local Windows app that can:
1) **Download video with title** (use video title as filename, sanitized for Windows).
2) Let user choose **download path to any directory**.
3) **Show file size and video length** (duration) for each item (before download if possible; always after download).
4) Support **multi-thread / accelerated downloads** (parallel fragment downloads where supported).
5) Support **multiple user accounts / profiles**, each with its own settings:
   - account input (at least: profile name + cookies/auth source + output folder default)
   - per-user option: **max number of downloads** or **max concurrent downloads**.
6) Provide option to **download by pasting one or more links** (single URL, multiple lines; support playlist URLs if possible).
7) Provide a **good clean UI** (simple, modern, uncluttered).
8) Check and display **FFmpeg/related tool versions** in UI to prevent errors (show status and exact versions).

Also add any sensible improvements that make the tool stable and user-friendly.

---

## 1) Platform / constraints
- OS: **Windows 10/11**
- Language: **Python 3.11+**
- UI: **PySide6 (Qt)**
- Must not require cloud services; everything runs locally.
- Must not delete or modify original downloads unexpectedly.

---

## 2) Recommended core tools (preferred)
Use these building blocks unless a strong reason not to:
- **yt-dlp** for extracting metadata and downloading video/audio.
- **FFmpeg + FFprobe** for muxing/processing and for accurate duration checks.
- Optional acceleration:
  - Prefer yt-dlp native concurrent fragments (`-N`) and/or external downloader **aria2c** if installed.

Important: If external tools (ffmpeg/ffprobe/aria2c) are missing, the app must:
- clearly show that in UI
- provide actionable instructions (where to install / how to set PATH)
- still work in a degraded mode if possible.

---

## 3) User experience requirements (UI)
### Main screen layout
- **Input box**: paste one or multiple URLs (one per line)
- Buttons: **Add to Queue**, **Start**, **Pause**, **Cancel Selected**, **Open Download Folder**
- Controls:
  - Output directory picker (browse)
  - Profile selector (multi user accounts)
  - Toggle: “Use title as filename” (default ON)
  - Toggle: “Download best quality” vs “Choose format”
  - Concurrency settings:
    - Global max concurrent downloads (default 2)
    - Per-download fragment threads (yt-dlp `-N`) (default 8)
    - Per-profile limit option (download count cap or concurrent cap)
- **Queue table** columns (minimum):
  - Status (Queued/Downloading/Done/Error)
  - Title
  - Source (domain)
  - Duration (hh:mm:ss)
  - Expected size (if available)
  - Downloaded / Total
  - Speed
  - ETA
  - Output path
- Bottom area:
  - Log panel (filterable; copy to clipboard)
  - Environment status: FFmpeg version, yt-dlp version, aria2 presence

### Clean UI rules
- Avoid clutter.
- Use consistent spacing, readable fonts, and simple icons.
- Dark mode optional (nice-to-have).
- Clear error messages and “How to fix” tips.

---

## 4) Functional requirements (download behavior)
### Filename/title
- Default filename: **sanitized title** + extension (Windows safe)
- Avoid collisions: if file exists, append ` (1)`, ` (2)` etc.
- Preserve original title in metadata view.

### Download path
- User can select any directory.
- Must validate write permissions and free disk space warnings (nice-to-have).

### Show size + length
- Before download (preferred):
  - Fetch metadata with yt-dlp and show:
    - duration
    - approximate filesize (if provided)
- After download (required):
  - Use **ffprobe** (or media parsing) to confirm duration
  - Show actual file size from filesystem

### Multi-thread download
- Use yt-dlp fragment concurrency (`-N`) where supported.
- If aria2c is available and user enables it, use it as external downloader.
- Provide a setting for fragment threads; do not exceed reasonable values by default.

### Multi-user accounts / profiles
Profiles must support:
- Profile name
- Default output directory (optional)
- Authentication method:
  - **Cookies file** path OR browser cookie import option (if supported by yt-dlp)
- Limits:
  - Max concurrent downloads for this profile (or max total downloads per run)
- Persist profiles locally (e.g., JSON/SQLite). Sensitive info handling:
  - Do not store passwords in plaintext.
  - Prefer cookies-based auth rather than raw username/password.

### Links-only mode
- User can paste links and download without additional prompts.
- For multiple links:
  - Add each as a queue item
  - Deduplicate identical links (optional toggle)

---

## 5) Reliability requirements
- Must never freeze the UI while downloading.
- Use a background worker model:
  - QThread / QRunnable with signals for progress
  - A queue manager controlling concurrency
- Robust cancellation:
  - Cancels active download process cleanly
  - Marks item as canceled, does not corrupt other downloads
- Logging:
  - Write a rolling log file to app data folder
  - Show logs in UI
- Errors:
  - Capture stderr from yt-dlp/ffmpeg
  - Show a friendly message + details toggle

---

## 6) Version / dependency checks (show in UI)
On app start and in a “Settings / About” panel, display:
- Python version
- yt-dlp version
- FFmpeg version and ffprobe availability
- aria2c availability and version (if installed)
Show status indicators:
- ✅ available
- ⚠️ missing / outdated
Provide a “Re-check” button.

If FFmpeg is missing:
- downloads may still happen, but warn that muxing/conversion and duration checks may fail.

---

## 7) Project structure (suggested)
- `app/`
  - `ui/` (Qt UI code)
  - `core/`
    - `download_manager.py` (queue, concurrency)
    - `ytdlp_client.py` (metadata + download invocation)
    - `ffmpeg_tools.py` (ffmpeg/ffprobe checks, duration)
    - `profiles.py` (profiles store/load)
    - `models.py` (dataclasses/pydantic models)
  - `resources/` (icons)
- `data/` (local dev data; not for production)
- `exports/` default output folder (optional)
- `tests/`

---

## 8) Improvements to include (nice-to-have, but valuable)
- Import/export profiles
- “Open file after download”
- “Copy title / Copy path / Copy link”
- Retry failed downloads (with retry limit)
- Duplicate detection by URL
- Playlist handling (add as multiple queue items with confirmation)
- Format selector dialog for advanced users
- Rate limit option (avoid network spikes)
- Disk space warning
- Auto-update checker for yt-dlp (optional)

---

## 9) Coding rules
- Keep code readable and modular.
- Use type hints.
- No long blocking operations on the UI thread.
- Prefer subprocess calls with controlled timeouts and safe argument handling.
- Security:
  - Never log cookies content.
  - Never store plaintext passwords.
  - Validate paths and sanitize filenames.

---

## 10) Acceptance criteria (definition of done)
A build is acceptable when:
- I can paste multiple links, pick any folder, pick a profile, and download.
- Each queue item shows title, duration, size, progress, speed, ETA.
- UI remains responsive.
- Multi-thread fragment download works and is configurable.
- Profiles persist and per-profile download/concurrency limits work.
- UI shows ffmpeg/ffprobe/yt-dlp versions and warns if missing.

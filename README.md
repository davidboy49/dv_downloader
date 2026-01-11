dv_downloader

Setup notes (Windows):
- FFmpeg: download from https://www.gyan.dev/ffmpeg/builds/ or https://ffmpeg.org/download.html, unzip, and add the `bin` folder to PATH.
- aria2c: install via https://github.com/aria2/aria2/releases (or `choco install aria2`), then add `aria2c.exe` to PATH.

PyInstaller build (Windows):
- Install deps: `pip install -r requirements.txt`
- Install packager: `pip install pyinstaller`
- Build: `.\scripts\build.ps1`
- Output: `dist\dv_downloader.exe`


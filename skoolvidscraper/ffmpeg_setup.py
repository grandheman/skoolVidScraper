import os
import shutil


def ensure_ffmpeg() -> bool:
    """
    Make sure ffmpeg is reachable by this process (yt-dlp merging + screenshots
    both need it). If it is not already on PATH, look in common install locations
    (notably winget's shim dir and package dir on Windows) and prepend the folder
    to PATH so child processes inherit it. Returns True if ffmpeg is available.
    """
    if shutil.which("ffmpeg"):
        return True

    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        r"C:\ffmpeg\bin",
        "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin",
    ]
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, exe)):
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            return True

    # winget installs the real binary under a versioned Packages subfolder
    winget = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget):
        for root, _dirs, files in os.walk(winget):
            if exe in files:
                os.environ["PATH"] = root + os.pathsep + os.environ["PATH"]
                return True

    print("WARNING: ffmpeg was not found. Video merging and screenshots will not "
          "work. Install it (Windows: winget install Gyan.FFmpeg) and restart.")
    return False

"""
System-tray wrapper: runs the local helper server in the background with a tray
icon, so there is no raw `python server.py` console to babysit. Right-click the
icon to Quit. Needs the optional [tray] extra:  pip install "skoolvidscraper[tray]"
"""
import socket
import threading
import webbrowser

from .server import PORT, app


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _make_icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), "#0f1115")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 12, 54, 52], radius=8, fill="#4f7cff")
    d.polygon([(27, 24), (27, 40), (42, 32)], fill="#ffffff")  # play triangle
    return img


def run():
    try:
        import pystray
    except ImportError:
        raise SystemExit(
            "Tray mode needs extra dependencies:\n"
            '  pip install "skoolvidscraper[tray]"\n'
            "  (or: pip install pystray pillow)"
        )

    from .ffmpeg_setup import ensure_ffmpeg
    ensure_ffmpeg()

    if _port_in_use(PORT):
        raise SystemExit(
            f"Port {PORT} is already in use - the server may already be running.\n"
            "Quit the existing instance first."
        )

    # Flask in a daemon thread; the tray icon owns the main thread.
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=PORT, threaded=True),
        daemon=True,
    ).start()

    def _open_extensions(icon, item):
        webbrowser.open("chrome://extensions")

    icon = pystray.Icon(
        "skoolvidscraper",
        _make_icon_image(),
        "skoolVidScraper",
        menu=pystray.Menu(
            pystray.MenuItem(f"Server: 127.0.0.1:{PORT}", None, enabled=False),
            pystray.MenuItem("Open chrome://extensions", _open_extensions),
            pystray.MenuItem("Quit", lambda icon, item: icon.stop()),
        ),
    )
    print(f"skoolVidScraper is running in the system tray (server on 127.0.0.1:{PORT}).")
    icon.run()

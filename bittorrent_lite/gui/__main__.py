"""
Start the browser GUI:

    python -m bittorrent_lite.gui [--port 8765] [--workdir ~/BitTorrentLite] [--no-browser] [--no-share]

Opens http://127.0.0.1:8765 in the default browser. Press Ctrl+C in this
terminal to stop the GUI; it stops its peers and tracker first.
"""

import argparse
import signal
import sys
import threading
import webbrowser
from pathlib import Path

from bittorrent_lite.gui.app import GuiApp
from bittorrent_lite.gui.server import make_server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BitTorrent-Lite browser GUI")
    parser.add_argument("--port", type=int, default=8765, help="port for the GUI page (default 8765)")
    parser.add_argument("--workdir", default=str(Path.home() / "BitTorrentLite"),
                        help="folder for torrents, downloads and logs (default ~/BitTorrentLite)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.add_argument("--no-share", action="store_true",
                        help="do not let other computers download this GUI's torrent files")
    args = parser.parse_args(argv)

    app = GuiApp(Path(args.workdir), args.port, share=not args.no_share)
    try:
        server = make_server(app, args.port, share=not args.no_share)
    except OSError as exc:
        print(f"Cannot use port {args.port}: {exc}. Is the GUI already open? Try --port 8766.", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{args.port}/"
    print(f"BitTorrent-Lite GUI: {url}")
    print(f"Working folder: {app.workdir}")
    if not args.no_share:
        print(f"Other computers join with this address: {app.state()['share_address']}")
    print("Press Ctrl+C to stop.")
    def interrupt(*_):
        raise KeyboardInterrupt
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, interrupt)     # closing the terminal also stops the children
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping peers and tracker...")
    finally:
        server.server_close()
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

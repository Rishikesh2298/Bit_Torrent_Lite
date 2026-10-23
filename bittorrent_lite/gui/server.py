"""
HTTP front end of the GUI: the page, a JSON API and the read-only share endpoint.

Only this computer may use the API: requests must come from a loopback
address, name a local Host (blocks DNS rebinding) and carry the X-BTL-GUI
header (a plain cross-site form cannot set it). Other computers can reach
only GET /share/index.json and GET /share/<file_id>.torrent.json.
"""

import ipaddress
import json
import mimetypes
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bittorrent_lite.gui.app import GuiApp, UserError

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 16 << 20
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "BitTorrentLiteGUI/1"
    app: GuiApp = None

    def log_message(self, fmt, *args):     # keep the terminal quiet; errors are shown in the page
        pass

    # ---------- plumbing ----------

    def _send(self, status, body: bytes, content_type: str, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, data):
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _local_request(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return _loopback(self.client_address[0]) and host in LOCAL_HOSTS

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise UserError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError as exc:
            raise UserError("bad JSON") from exc
        if not isinstance(data, dict):
            raise UserError("bad JSON")
        return data

    # ---------- GET ----------

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if path.startswith("/share/"):
            return self._share(path)
        if not self._local_request():
            return self._json(403, {"error": "this page only works on the computer running the GUI"})
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/api/state":
                return self._json(200, self.app.state(selected=query.get("peer")))
            if path == "/api/fs":
                return self._json(200, self.app.list_dir(query.get("path")))
            if path == "/api/experiments":
                return self._json(200, self.app.experiment_info())
            match = re.fullmatch(r"/api/torrents/([0-9a-f]{64})/file", path)
            if match:
                entry = self.app.torrent(match.group(1))
                data = Path(entry["path"]).read_bytes()
                name = Path(entry["path"]).name
                return self._send(200, data, "application/json",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
            match = re.fullmatch(r"/api/experiments/figures/([A-Za-z0-9_.-]+\.png)", path)
            if match:
                return self._send(200, self.app.figure_path(match.group(1)).read_bytes(), "image/png")
        except UserError as exc:
            return self._json(400, {"error": str(exc)})
        except KeyError:
            return self._json(404, {"error": "not found"})
        return self._static(path)

    def _share(self, path):
        if not self.app.share:
            return self._json(404, {"error": "sharing is turned off on this computer"})
        if path == "/share/index.json":
            return self._json(200, self.app.share_index())
        match = re.fullmatch(r"/share/([0-9a-f]{64})\.torrent\.json", path)
        if match:
            try:
                return self._send(200, self.app.share_file(match.group(1)), "application/json")
            except (KeyError, OSError):
                pass
        return self._json(404, {"error": "not shared"})

    def _static(self, path):
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        target = (STATIC / name).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self._json(404, {"error": "not found"})
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith("javascript"):
            kind += "; charset=utf-8"
        self._send(200, target.read_bytes(), kind)

    # ---------- POST ----------

    ROUTES = {
        "/api/settings": lambda app, b: app.update_settings(b),
        "/api/addresses/refresh": lambda app, b: app.refresh_addresses(),
        "/api/tracker/start": lambda app, b: app.start_tracker(b.get("port")),
        "/api/tracker/stop": lambda app, b: app.stop_tracker(),
        "/api/tracker/test": lambda app, b: app.test_tracker(b.get("url")),
        "/api/torrents/create": lambda app, b: app.create_torrent(b),
        "/api/torrents/open": lambda app, b: app.open_torrent(str(b.get("path", ""))),
        "/api/torrents/upload": lambda app, b: app.import_torrent_text(str(b.get("name", "")), str(b.get("text", ""))),
        "/api/torrents/source": lambda app, b: app.set_source(b.get("file_id"), str(b.get("source", ""))),
        "/api/torrents/remove": lambda app, b: app.remove_torrent(b.get("file_id")),
        "/api/join": lambda app, b: app.join(str(b.get("address", ""))),
        "/api/join/fetch": lambda app, b: app.fetch_shared(str(b.get("address", "")), str(b.get("file_id", ""))),
        "/api/peers/suggest": lambda app, b: app.suggest(b),
        "/api/peers/preview": lambda app, b: app.preview(b),
        "/api/peers/start": lambda app, b: app.start_peers(b),
        "/api/peers/stop": lambda app, b: app.stop_peer(str(b.get("peer_id"))),
        "/api/peers/stop_all": lambda app, b: app.stop_all(b.get("file_id")),
        "/api/peers/restart": lambda app, b: app.restart_peer(str(b.get("peer_id"))),
        "/api/peers/remove": lambda app, b: app.remove_peer(str(b.get("peer_id"))),
        "/api/open_folder": lambda app, b: app.open_folder(str(b.get("path", ""))),
        "/api/experiments/run": lambda app, b: app.run_experiments(b),
        "/api/experiments/stop": lambda app, b: app.stop_experiments(),
    }

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self._local_request() or self.headers.get("X-BTL-GUI") != "1":
            return self._json(403, {"error": "forbidden"})
        route = self.ROUTES.get(path)
        if route is None:
            return self._json(404, {"error": "not found"})
        try:
            return self._json(200, route(self.app, self._body()))
        except UserError as exc:
            return self._json(400, {"error": str(exc)})
        except (OSError, ValueError, TypeError) as exc:
            traceback.print_exc()
            return self._json(400, {"error": f"{type(exc).__name__}: {exc}"})


def make_server(app: GuiApp, port: int, share: bool) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("0.0.0.0" if share else "127.0.0.1", port), handler)
    server.daemon_threads = True
    return server

"""
The GUI's controller: settings, known torrents, peers, tracker and experiments.

Everything the browser can do goes through one GuiApp object. It never
changes the backend: it starts the project's command-line programs and reads
their files and output.
"""

import csv
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from bittorrent_lite.common.config import TRACKER_PORT
from bittorrent_lite.gui import netinfo
from bittorrent_lite.gui.processes import (JobProcess, PeerProcess, TrackerProcess, child_env,
                                           module_command, peer_arguments, NO_WINDOW)
from bittorrent_lite.storage.metadata import load_metadata

DEFAULT_GUI_PORT = 8765
MAX_NETWORK_PIECE = 65536           # network_backend.validate_network_inputs refuses larger pieces
EXPERIMENT_CONFIGS = [
    ("swarm-L2", "2 downloaders"), ("swarm-L4", "4 downloaders"), ("swarm-L6", "6 downloaders (baseline)"),
    ("swarm-L8", "8 downloaders"), ("select-random", "random pieces"), ("select-sequential", "sequential pieces"),
    ("seeders-S2", "2 seeders"), ("free-rider", "1 free rider"), ("failure", "peer killed at 25%"),
]


# Talk to other computers directly: a system HTTP proxy cannot reach Tailscale or LAN addresses.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class UserError(Exception):
    """A problem the person can fix; shown in the page as is."""


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "bittorrent_lite").is_dir():
            return parent
    return None


class GuiApp:
    def __init__(self, workdir: Path, gui_port: int, share: bool):
        self.workdir = workdir.expanduser().resolve()
        self.gui_port = gui_port
        self.instance = secrets.token_hex(8)
        self.share = share
        self.lock = threading.RLock()
        for sub in ("torrents", "downloads", ".gui/logs", ".gui/stop"):
            (self.workdir / sub).mkdir(parents=True, exist_ok=True)
        for stale in (self.workdir / ".gui" / "stop").glob("*"):
            stale.unlink(missing_ok=True)
        self.settings_path = self.workdir / ".gui" / "settings.json"
        self.settings = self._load_settings()
        self.addresses = netinfo.local_addresses()
        if self.settings.get("advertise_ip") not in {a["ip"] for a in self.addresses}:
            self.settings["advertise_ip"] = netinfo.default_address(self.addresses)
        self.torrents = {}
        for path in self.settings.get("torrents", []):
            try:
                self._register_torrent(Path(path), save=False)
            except UserError:
                pass
        self.peers = {}
        self.tracker = None
        self.experiment = None
        self.experiment_state = {"status": "idle", "planned": 0, "done": 0, "current": None,
                                 "message": "", "lines": []}
        self._save_settings()

    # ---------- settings ----------

    def _load_settings(self) -> dict:
        try:
            data = json.loads(self.settings_path.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        with self.lock:
            self.settings["torrents"] = [t["path"] for t in self.torrents.values()]
            tmp = self.settings_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.settings, indent=2), "utf-8")
            tmp.replace(self.settings_path)

    def tracker_url(self) -> str:
        url = self.settings.get("tracker_url")
        if url:
            return url
        return f"http://{self.settings['advertise_ip']}:{self.settings.get('tracker_port', TRACKER_PORT)}"

    def update_settings(self, body: dict) -> dict:
        with self.lock:
            if "advertise_ip" in body:
                ip = str(body["advertise_ip"])
                if ip not in {a["ip"] for a in self.addresses}:
                    raise UserError(f"{ip} is not an address of this computer")
                old_local = self._local_tracker_url()
                self.settings["advertise_ip"] = ip
                if self.settings.get("tracker_url") in (None, old_local):
                    self.settings["tracker_url"] = None
            if "tracker_url" in body:
                url = (body["tracker_url"] or "").strip()
                self.settings["tracker_url"] = self._normalise_tracker(url) if url else None
            self._save_settings()
        return self.state()

    def _local_tracker_url(self) -> str:
        return f"http://{self.settings['advertise_ip']}:{self.settings.get('tracker_port', TRACKER_PORT)}"

    @staticmethod
    def _normalise_tracker(text: str) -> str:
        if "://" not in text:
            text = "http://" + text
        url = urlsplit(text)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise UserError("tracker must look like http://100.101.102.103:8000")
        port = url.port or TRACKER_PORT
        return f"{url.scheme}://{url.hostname}:{port}"

    def refresh_addresses(self) -> dict:
        self.addresses = netinfo.local_addresses()
        if self.settings.get("advertise_ip") not in {a["ip"] for a in self.addresses}:
            self.settings["advertise_ip"] = netinfo.default_address(self.addresses)
            self._save_settings()
        return self.state()

    # ---------- tracker ----------

    def start_tracker(self, port: int | None = None) -> dict:
        with self.lock:
            if self.tracker and self.tracker.running:
                raise UserError("the tracker is already running")
            port = int(port or self.settings.get("tracker_port") or TRACKER_PORT)
            if not netinfo.port_is_free(port):
                raise UserError(f"port {port} is busy; is another tracker already running?")
            self.settings["tracker_port"] = port
            self.settings["tracker_url"] = None          # local peers use this computer's tracker
            self._save_settings()
            self.tracker = TrackerProcess(port, self.workdir)
        deadline = time.time() + 5
        while time.time() < deadline and not self.tracker.ready and self.tracker.running:
            time.sleep(0.1)
        if not self.tracker.running:
            raise UserError("tracker exited: " + " ".join(l["text"] for l in list(self.tracker.lines)[-3:]))
        return self.state()

    def stop_tracker(self) -> dict:
        if self.tracker and self.tracker.running:
            self.tracker.terminate()
            for _ in range(30):
                if not self.tracker.running:
                    break
                time.sleep(0.1)
            if self.tracker.running:
                self.tracker.kill()
        return self.state()

    @staticmethod
    def probe_tracker(url: str, timeout: float = 3) -> dict:
        """The tracker answers GET /announce with 405 JSON, which proves it is alive."""
        try:
            _DIRECT.open(url.rstrip("/") + "/announce", timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                return {"ok": True, "message": "tracker is reachable"}
            return {"ok": False, "message": f"something answered with HTTP {exc.code}, but not a tracker"}
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return {"ok": False, "message": f"cannot reach {url}: {reason}"}
        return {"ok": False, "message": "something answered, but not a tracker"}

    def test_tracker(self, url: str | None) -> dict:
        target = self._normalise_tracker(url) if url else self.tracker_url()
        return {"url": target, **self.probe_tracker(target)}

    # ---------- torrents ----------

    def _register_torrent(self, path: Path, *, source: str | None = None, save: bool = True,
                          origin: str = "local") -> dict:
        path = path.expanduser().resolve()
        try:
            metadata, file_id = load_metadata(str(path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise UserError(f"not a valid .torrent.json: {exc}") from exc
        with self.lock:
            existing = self.torrents.get(file_id, {})
            entry = {
                "file_id": file_id, "path": str(path), "filename": metadata.filename,
                "file_size": metadata.file_size, "piece_size": metadata.piece_size,
                "num_pieces": metadata.num_pieces, "file_sha256": metadata.file_sha256,
                "source": source or existing.get("source") or self.settings.get("sources", {}).get(file_id),
                "origin": existing.get("origin", origin), "added": existing.get("added", time.time()),
                "network_ok": metadata.piece_size <= MAX_NETWORK_PIECE,
            }
            if entry["source"]:
                self.settings.setdefault("sources", {})[file_id] = entry["source"]
            self.torrents[file_id] = entry
            if save:
                self._save_settings()
            return entry

    def torrent(self, file_id: str) -> dict:
        try:
            return self.torrents[file_id]
        except KeyError:
            raise UserError("unknown torrent; open its .torrent.json first") from None

    def create_torrent(self, body: dict) -> dict:
        source = Path(str(body.get("source", ""))).expanduser()
        if not source.is_file():
            raise UserError("choose an existing source file")
        piece_size = int(body.get("piece_size") or MAX_NETWORK_PIECE)
        if not 1024 <= piece_size <= MAX_NETWORK_PIECE:
            raise UserError("piece size must be between 1 KiB and 64 KiB (the network limit)")
        output = body.get("output") or str(self.workdir / "torrents" / f"{source.name}.torrent.json")
        output = Path(output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        command = module_command("bittorrent_lite.storage.generate_metadata", "--file", source.resolve(),
                                 "--output", output, "--piece-size", piece_size)
        result = subprocess.run(command, capture_output=True, text=True, env=child_env(),
                                cwd=str(self.workdir), creationflags=NO_WINDOW, timeout=3600)
        if result.returncode != 0:
            message = (result.stderr.strip().splitlines() or ["metadata generation failed"])[-1]
            raise UserError(message.replace("generate_metadata.py: error: ", ""))
        entry = self._register_torrent(output, source=str(source.resolve()), origin="created")
        return {"torrent": entry, "output": result.stdout, "command": subprocess.list2cmdline(command)}

    def open_torrent(self, path: str) -> dict:
        return {"torrent": self._register_torrent(Path(path), origin="opened")}

    def import_torrent_text(self, name: str, text: str, origin: str = "uploaded") -> dict:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise UserError("that file is not JSON") from exc
        if not isinstance(data, dict) or "filename" not in data:
            raise UserError("that JSON is not a BitTorrent-Lite torrent")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(data["filename"]))[:80] or "download"
        target = self.workdir / "torrents" / f"{safe}.torrent.json"
        target.write_text(text, "utf-8")
        return {"torrent": self._register_torrent(target, origin=origin)}

    def set_source(self, file_id: str, source: str) -> dict:
        entry = self.torrent(file_id)
        path = Path(source).expanduser()
        if not path.is_file():
            raise UserError("source file does not exist")
        if path.stat().st_size != entry["file_size"]:
            raise UserError(f"size differs from the torrent ({entry['file_size']} bytes)")
        return {"torrent": self._register_torrent(Path(entry["path"]), source=str(path.resolve()))}

    def remove_torrent(self, file_id: str) -> dict:
        with self.lock:
            if any(p.running and p.torrent["file_id"] == file_id for p in self.peers.values()):
                raise UserError("stop this torrent's peers first")
            self.torrents.pop(file_id, None)
            self.peers = {k: p for k, p in self.peers.items() if p.torrent["file_id"] != file_id}
            self._save_settings()
        return self.state()

    def share_index(self) -> dict:
        tracker = None
        if self.tracker and self.tracker.running:
            tracker = self._local_tracker_url()
        elif self.settings.get("tracker_url"):
            tracker = self.settings["tracker_url"]
        return {"app": "bittorrent-lite-gui", "instance": self.instance, "machine": netinfo.machine_tag(), "tracker": tracker,
                "torrents": [{k: t[k] for k in ("file_id", "filename", "file_size", "num_pieces", "piece_size")}
                             for t in self.torrents.values()]}

    def share_file(self, file_id: str) -> bytes:
        entry = self.torrents.get(file_id)
        if not entry:
            raise KeyError(file_id)
        return Path(entry["path"]).read_bytes()

    # ---------- joining another computer ----------

    @staticmethod
    def _host_base(address: str, default_port: int) -> str:
        text = address.strip()
        if not text:
            raise UserError("type the other computer's address, for example 100.101.102.103")
        if "://" not in text:
            text = "http://" + text
        url = urlsplit(text)
        if not url.hostname:
            raise UserError("that does not look like an address")
        return f"http://{url.hostname}:{url.port or default_port}"

    def join(self, address: str) -> dict:
        base = self._host_base(address, DEFAULT_GUI_PORT)
        try:
            with _DIRECT.open(base + "/share/index.json", timeout=5) as response:
                index = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise UserError(f"no BitTorrent-Lite GUI answered at {base}: {getattr(exc, 'reason', exc)}. "
                            "Is the GUI open on that computer, and are both on Tailscale or the same Wi-Fi?") from exc
        if index.get("app") != "bittorrent-lite-gui":
            raise UserError(f"{base} is not a BitTorrent-Lite GUI")
        if index.get("instance") == self.instance:
            raise UserError("that address is this computer's own GUI; type the sharing computer's address")
        tracker = index.get("tracker")
        if tracker:
            # The host advertises its own address; use the one we reached it on if that differs.
            host = urlsplit(base).hostname
            tracker = f"http://{host}:{urlsplit(tracker).port or TRACKER_PORT}"
            with self.lock:
                self.settings["tracker_url"] = tracker
                self.settings["last_host"] = address.strip()
                self._save_settings()
        with self.lock:
            for item in index.get("torrents", []):
                item["have"] = item.get("file_id") in self.torrents
        return {"base": base, "machine": index.get("machine"), "tracker": tracker,
                "tracker_check": self.probe_tracker(tracker) if tracker else None,
                "torrents": index.get("torrents", [])}

    def fetch_shared(self, address: str, file_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", file_id or ""):
            raise UserError("bad torrent id")
        base = self._host_base(address, DEFAULT_GUI_PORT)
        try:
            with _DIRECT.open(f"{base}/share/{file_id}.torrent.json", timeout=10) as response:
                text = response.read(16 << 20).decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            raise UserError(f"could not download the torrent: {getattr(exc, 'reason', exc)}") from exc
        result = self.import_torrent_text("shared", text, origin="joined")
        if result["torrent"]["file_id"] != file_id:
            raise UserError("the downloaded torrent does not match the one listed")
        return result

    # ---------- peers ----------

    def _taken_ids(self) -> set:
        taken = {p for p, proc in self.peers.items()}
        if self.tracker:
            for swarm in self.tracker.snapshot()["members"].values():
                taken.update(m["peer_id"] for m in swarm)
        return taken

    def _taken_ports(self) -> set:
        ports = {int(p.spec["port"]) for p in self.peers.values() if p.running}
        if self.tracker and self.tracker.running:
            ports.add(self.tracker.port)
        ports.add(self.gui_port)
        return ports

    def suggest(self, body: dict) -> dict:
        role = body.get("role", "downloader")
        count = max(1, min(int(body.get("count") or 1), 8)) if role == "downloader" else 1
        taken = self._taken_ids()
        ports = self._taken_ports()
        rows = []
        start = int(body.get("port_from") or 9000)
        for _ in range(count):
            peer_id = netinfo.new_peer_id(taken, seeder=(role == "seeder"))
            taken.add(peer_id)
            port = netinfo.next_free_port(start, ports)
            ports.add(port)
            start = port + 1
            rows.append({"peer_id": peer_id, "port": port})
        return {"peers": rows, "tracker_url": self.tracker_url(),
                "output_dir": str(self.workdir / "downloads")}

    def _spec(self, body: dict, entry: dict) -> dict:
        role = body.get("role", "downloader")
        if role not in ("seeder", "downloader"):
            raise UserError("role must be seeder or downloader")
        strategy = body.get("strategy", "rarest-first")
        if strategy not in ("rarest-first", "random", "sequential"):
            raise UserError("unknown piece selection strategy")
        window = int(body.get("window") or 4)
        if not 1 <= window <= 4:
            raise UserError("requests in flight must be 1 to 4")
        workers = int(body.get("upload_workers") or 0)
        if workers not in (0, 2):
            raise UserError("upload workers must be off or 2")
        spec = {"role": role, "strategy": strategy, "window": window, "upload_workers": workers,
                "seed": int(body.get("seed") or 0), "free_rider": bool(body.get("free_rider")),
                "output_dir": str(Path(body.get("output_dir") or self.workdir / "downloads").expanduser())}
        if role == "seeder":
            source = body.get("source") or entry.get("source")
            if not source or not Path(source).expanduser().is_file():
                raise UserError("a seeder needs the original file; choose it as the source file")
            if Path(source).expanduser().stat().st_size != entry["file_size"]:
                raise UserError("the source file's size does not match the torrent")
            spec["source"] = str(Path(source).expanduser().resolve())
        return spec

    def _check_config(self, spec: dict, entry: dict, peer_id: str, port: int) -> dict:
        """Run the peer's own --check-config so the person sees its verdict before starting."""
        args = ["--peer-id", peer_id, "--port", port, "--metadata", entry["path"],
                "--tracker", self.tracker_url(), "--output-dir", spec["output_dir"],
                "--strategy", spec["strategy"], "--window", spec["window"], "--check-config"]
        if spec["role"] == "seeder":
            args += ["--seeder", "--file", spec["source"]]
        result = subprocess.run(module_command("bittorrent_lite", *args), capture_output=True, text=True,
                                env=child_env(), cwd=str(self.workdir), creationflags=NO_WINDOW, timeout=120)
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr.strip() or "configuration rejected").splitlines()[-1]}
        try:
            info = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            info = {}
        return {"ok": True, "message": f"Settings checked: {info.get('num_pieces', '?')} pieces, "
                                       f"file_id {str(info.get('file_id', ''))[:6]}…{str(info.get('file_id', ''))[-4:]}"}

    def preview(self, body: dict) -> dict:
        entry = self.torrent(body.get("file_id"))
        spec = self._spec(body, entry)
        peer_id = body.get("peer_id") or "preview"
        port = int(body.get("port") or 9000)
        check = self._check_config(spec, entry, peer_id, port)
        args = peer_arguments({"peer_id": peer_id, "port": port, **spec}, entry,
                              self.workdir / ".gui" / "stop" / peer_id, self.tracker_url())
        return {"check": check, "command": subprocess.list2cmdline(module_command("bittorrent_lite", *args)),
                "warnings": self._warnings(entry)}

    def _warnings(self, entry: dict) -> list:
        warnings = []
        if not entry.get("network_ok", True):
            warnings.append("This torrent's pieces are larger than 64 KiB, which peers refuse. Recreate it with 64 KiB pieces.")
        url = urlsplit(self.tracker_url())
        if url.hostname in ("127.0.0.1", "localhost") and any(a["kind"] != "loopback" for a in self.addresses):
            warnings.append("The tracker address is 127.0.0.1, so peers on other computers cannot reach this one. "
                            "Pick this computer's Tailscale or LAN address in Network settings.")
        return warnings

    def start_peers(self, body: dict) -> dict:
        entry = self.torrent(body.get("file_id"))
        spec = self._spec(body, entry)
        requested = body.get("peers") or []
        if not requested:
            requested = self.suggest({"role": spec["role"], "count": body.get("count", 1)})["peers"]
        started = []
        with self.lock:
            taken = self._taken_ids()
            ports = self._taken_ports()
            for row in requested:
                peer_id = str(row.get("peer_id", "")).strip()
                port = int(row.get("port") or 0)
                if not netinfo.PEER_ID_RE.fullmatch(peer_id):
                    raise UserError("peer ID must be 1-32 letters, digits, '-' or '_'")
                if peer_id in taken:
                    raise UserError(f"peer ID {peer_id} is already in use; two peers with one ID stall")
                if not 1 <= port <= 65535 or port in ports or not netinfo.port_is_free(port):
                    raise UserError(f"port {port} is busy; pick another")
                taken.add(peer_id)
                ports.add(port)
                proc = PeerProcess({"peer_id": peer_id, "port": port, **spec}, entry, self.workdir,
                                   self.tracker_url())
                self.peers[peer_id] = proc
                started.append(peer_id)
        return {"started": started, **self.state()}

    def peer(self, peer_id: str) -> PeerProcess:
        try:
            return self.peers[peer_id]
        except KeyError:
            raise UserError("unknown peer") from None

    def stop_peer(self, peer_id: str) -> dict:
        self.peer(peer_id).request_stop()
        return self.state()

    def stop_all(self, file_id: str | None = None) -> dict:
        for proc in list(self.peers.values()):
            if file_id is None or proc.torrent["file_id"] == file_id:
                proc.request_stop()
        return self.state()

    def restart_peer(self, peer_id: str) -> dict:
        old = self.peer(peer_id)
        if old.running:
            raise UserError("stop the peer before restarting it")
        entry = self.torrent(old.torrent["file_id"])
        with self.lock:
            if not netinfo.port_is_free(int(old.spec["port"])):
                old.spec["port"] = netinfo.next_free_port(int(old.spec["port"]) + 1, self._taken_ports())
            self.peers[peer_id] = PeerProcess(old.spec, entry, self.workdir, self.tracker_url())
        return self.state()

    def remove_peer(self, peer_id: str) -> dict:
        proc = self.peer(peer_id)
        if proc.running:
            raise UserError("stop the peer first")
        with self.lock:
            self.peers.pop(peer_id, None)
        return self.state()

    # ---------- experiments ----------

    def experiment_info(self) -> dict:
        root = _repo_root()
        missing = [name for name in ("matplotlib", "pandas", "numpy") if importlib.util.find_spec(name) is None]
        results = root / "bittorrent_lite" / "experiments" / "results" if root else None
        bars = {}
        if results and (results / "runs.csv").is_file():
            try:
                with open(results / "runs.csv", newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        if row.get("status") == "ok" and row.get("distribution_s"):
                            bars.setdefault(row.get("config_name") or row.get("run_id"), []).append(
                                float(row["distribution_s"]))
            except (OSError, ValueError):
                bars = {}
        figures = sorted(p.name for p in (results / "figures").glob("*.png")) if results and (results / "figures").is_dir() else []
        return {"available": root is not None, "missing": missing,
                "configs": [{"name": n, "desc": d} for n, d in EXPERIMENT_CONFIGS],
                "results": [{"name": n, "mean": sum(v) / len(v), "min": min(v), "max": max(v), "n": len(v)}
                            for n, v in sorted(bars.items(), key=lambda kv: [c[0] for c in EXPERIMENT_CONFIGS].index(kv[0])
                                               if kv[0] in [c[0] for c in EXPERIMENT_CONFIGS] else 99)],
                "figures": figures, "results_dir": str(results) if results else None,
                "job": dict(self.experiment_state, lines=self.experiment_state["lines"][-12:])}

    def figure_path(self, name: str) -> Path:
        root = _repo_root()
        if not root or not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", name):
            raise KeyError(name)
        path = root / "bittorrent_lite" / "experiments" / "results" / "figures" / name
        if not path.is_file():
            raise KeyError(name)
        return path

    def run_experiments(self, body: dict) -> dict:
        root = _repo_root()
        if root is None:
            raise UserError("experiments need the project's source folder (run the GUI from the repository)")
        info = self.experiment_info()
        if info["missing"]:
            raise UserError("install the experiments extra first: python -m pip install -e \".[experiments]\" "
                            f"(missing {', '.join(info['missing'])})")
        if self.experiment and self.experiment.running:
            raise UserError("an experiment run is already in progress")
        names = [n for n in body.get("configs", []) if n in dict(EXPERIMENT_CONFIGS)]
        if not names:
            raise UserError("select at least one configuration")
        repeats = max(1, min(int(body.get("repeats") or 1), 5))
        busy = [p for p in self.peers.values() if p.running]
        if busy:
            raise UserError("stop the running peers first; experiments need an idle machine")
        data = root / "bittorrent_lite" / "experiments" / "data"
        steps = []
        if not (data / "fixture.bin").is_file() or not (data / "fixture.torrent.json").is_file():
            steps.append(("fixture", module_command("bittorrent_lite.experiments.scripts.make_fixture")))
        matrix = ["bittorrent_lite.experiments.scripts.matrix",
                  str(root / "bittorrent_lite" / "experiments" / "configs" / "base.json"),
                  "--repeats", str(repeats), "--set", "tracker_port=18000", "--set", "base_port=17001"]
        for name in names:
            matrix += ["--only", name]
        steps.append(("matrix", module_command(*matrix)))
        steps.append(("plot", module_command("bittorrent_lite.experiments.scripts.plot")))
        self.experiment_state = {"status": "running", "planned": len(names) * repeats, "done": 0,
                                 "current": None, "message": "starting", "lines": [], "started_at": time.time()}
        self._run_steps(steps, root)
        return self.experiment_info()

    def _run_steps(self, steps, root):
        state = self.experiment_state

        def on_line(line, stream):
            state["lines"].append(line)
            del state["lines"][:-200]
            match = re.match(r"\[(\d+)/(\d+)\] (\S+): (\w+)", line)
            if match:
                state["done"], state["planned"] = int(match.group(1)), int(match.group(2))
                state["message"] = f"{match.group(3)}: {match.group(4)}"
            elif re.match(r"(\d+) run\(s\) planned", line):
                state["planned"] = int(line.split()[0])

        def on_done(code):
            if state["status"] == "stopped":
                return
            if code != 0:
                state["failed_step"] = state["current"]
            # A failed matrix still gets its finished runs plotted.
            if steps and (code == 0 or steps[0][0] == "plot"):
                launch()
            elif code == 0 and not state.get("failed_step"):
                state["status"], state["message"] = "done", "finished; figures redrawn"
            else:
                state["status"] = "failed"
                state["message"] = f"the {state.get('failed_step')} step failed; see the last lines below"

        def launch():
            name, command = steps.pop(0)
            state["current"] = name
            state["message"] = {"fixture": "creating the 32 MiB test file", "matrix": "running",
                                "plot": "drawing figures"}[name]
            self.experiment = JobProcess(f"experiments-{name}", command, root, on_line, on_done)

        launch()

    def stop_experiments(self) -> dict:
        if self.experiment and self.experiment.running:
            self.experiment_state["status"] = "stopped"
            self.experiment_state["message"] = "stopped by you; finished runs are kept"
            self.experiment.kill()
        return self.experiment_info()

    # ---------- files ----------

    @staticmethod
    def list_dir(path: str | None) -> dict:
        roots = [str(Path.home())]
        if os.name == "nt":
            roots += [f"{d}:\\" for d in "CDEFGHIJ" if Path(f"{d}:\\").exists()]
        else:
            roots += ["/"] + (["/Volumes"] if Path("/Volumes").is_dir() else [])
        folder = Path(path).expanduser() if path else Path.home()
        if folder.is_file():
            folder = folder.parent
        if not folder.is_dir():
            raise UserError(f"{folder} is not a folder")
        entries = []
        try:
            for child in folder.iterdir():
                if child.name.startswith("."):
                    continue
                try:
                    is_dir = child.is_dir()
                    size = None if is_dir else child.stat().st_size
                except OSError:
                    continue
                entries.append({"name": child.name, "path": str(child), "dir": is_dir, "size": size})
        except PermissionError as exc:
            raise UserError(f"no permission to read {folder}") from exc
        entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        parent = str(folder.parent) if folder.parent != folder else None
        return {"path": str(folder.resolve()), "parent": parent, "entries": entries[:2000], "roots": roots}

    @staticmethod
    def open_folder(path: str) -> dict:
        target = Path(path).expanduser()
        if target.is_file():
            target = target.parent
        if not target.exists():
            raise UserError(f"{target} does not exist yet")
        if os.name == "nt":
            os.startfile(str(target))  # noqa: S606 - opens Explorer on the person's own folder
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(target)])
        else:
            raise UserError(f"open this folder yourself: {target}")
        return {"ok": True}

    # ---------- state for the page ----------

    def state(self, selected: str | None = None) -> dict:
        with self.lock:
            peers = [p.snapshot(detail=(p.peer_id == selected)) for p in self.peers.values()]
            tracker = self.tracker.snapshot() if self.tracker else None
            return {
                "machine": netinfo.machine_tag(), "workdir": str(self.workdir), "gui_port": self.gui_port,
                "share": self.share, "addresses": self.addresses, "advertise_ip": self.settings["advertise_ip"],
                "tracker_url": self.tracker_url(), "tracker_custom": bool(self.settings.get("tracker_url")),
                "last_host": self.settings.get("last_host", ""), "tracker": tracker,
                "torrents": sorted(self.torrents.values(), key=lambda t: t["added"]),
                "peers": peers, "experiment": dict(self.experiment_state, lines=[]),
                "share_address": f"{self.settings['advertise_ip']}" + (
                    "" if self.gui_port == DEFAULT_GUI_PORT else f":{self.gui_port}"),
            }

    def shutdown(self):
        for proc in list(self.peers.values()):
            proc.request_stop()
        deadline = time.time() + 8
        while time.time() < deadline and any(p.running for p in self.peers.values()):
            time.sleep(0.2)
        for proc in self.peers.values():
            if proc.running:
                proc.kill()
        if self.experiment and self.experiment.running:
            self.experiment.kill()
        if self.tracker and self.tracker.running:
            self.tracker.terminate()

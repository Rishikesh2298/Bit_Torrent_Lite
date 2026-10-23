"""Drive the GUI's HTTP API the way the page does: tracker, torrent, seeder, downloader, hash check."""
import json
import os
import time
import urllib.error
import urllib.request
from threading import Thread

import pytest

from bittorrent_lite.gui import netinfo
from bittorrent_lite.gui.app import GuiApp
from bittorrent_lite.gui.server import make_server

pytestmark = pytest.mark.timeout(120)
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setattr(netinfo, "_tailscale_cli", lambda: [])
    port = netinfo.next_free_port(18765)
    app = GuiApp(tmp_path / "work dir", port, share=True)
    app.settings["tracker_port"] = netinfo.next_free_port(18000)
    server = make_server(app, port, share=True)
    Thread(target=server.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    app.shutdown()


def call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers={"X-BTL-GUI": "1", **(headers or {})})
    with DIRECT.open(request, timeout=30) as response:
        return json.loads(response.read())


def wait_for(predicate, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError("condition not reached in time")


def test_seed_download_and_verify_through_the_api(gui, tmp_path):
    app, base = gui
    source = tmp_path / "lecture video.bin"
    source.write_bytes(os.urandom(65536 * 5 + 321))

    state = call(base, "/api/tracker/start", {})
    assert state["tracker"]["running"]
    created = call(base, "/api/torrents/create", {"source": str(source), "piece_size": 32768})
    file_id = created["torrent"]["file_id"]
    assert created["torrent"]["num_pieces"] == 11

    preview = call(base, "/api/peers/preview", {"file_id": file_id, "role": "seeder", "peer_id": "x", "port": 9})
    assert preview["check"]["ok"], preview
    call(base, "/api/peers/start", {"file_id": file_id, "role": "seeder"})
    started = call(base, "/api/peers/start", {"file_id": file_id, "role": "downloader", "count": 2})["started"]
    assert len(started) == 2 and len(set(started)) == 2

    def downloaded():
        peers = call(base, "/api/state")["peers"]
        down = [p for p in peers if p["role"] == "downloader"]
        return all(p["hash_check"] == "ok" for p in down) and down
    for peer in wait_for(downloaded):
        assert peer["state"] == "DONE"
        assert peer["owned"] == peer["total"] == 11
        with open(peer["output_file"], "rb") as handle:
            assert handle.read() == source.read_bytes()

    detail = call(base, f"/api/state?peer={started[0]}")
    selected = next(p for p in detail["peers"] if p["peer_id"] == started[0])
    assert selected["pieces"] == "v" * 11
    assert any(e["e"] == "COMPLETE" for e in selected["events"])

    call(base, "/api/peers/stop_all", {"file_id": file_id})
    wait_for(lambda: all(not p["running"] for p in call(base, "/api/state")["peers"]), timeout=30)
    assert all(p["state"] == "STOPPED" for p in call(base, "/api/state")["peers"])

    # Restart keeps verified pieces: the downloader comes back already complete.
    call(base, "/api/peers/restart", {"peer_id": started[0]})
    wait_for(lambda: next(p for p in call(base, "/api/state")["peers"] if p["peer_id"] == started[0])["state"] == "DONE")


def test_duplicate_peer_id_is_refused(gui, tmp_path):
    app, base = gui
    source = tmp_path / "a.bin"
    source.write_bytes(b"x" * 1000)
    file_id = call(base, "/api/torrents/create", {"source": str(source)})["torrent"]["file_id"]
    call(base, "/api/peers/start", {"file_id": file_id, "role": "downloader", "peers": [{"peer_id": "same", "port": netinfo.next_free_port(19100)}]})
    with pytest.raises(urllib.error.HTTPError) as error:
        call(base, "/api/peers/start", {"file_id": file_id, "role": "downloader", "peers": [{"peer_id": "same", "port": netinfo.next_free_port(19200)}]})
    assert error.value.code == 400
    assert "already in use" in json.loads(error.value.read())["error"]


def test_share_endpoint_is_read_only_and_api_needs_the_header(gui, tmp_path):
    app, base = gui
    source = tmp_path / "b.bin"
    source.write_bytes(b"y" * 5000)
    torrent = call(base, "/api/torrents/create", {"source": str(source)})["torrent"]
    index = json.loads(DIRECT.open(base + "/share/index.json").read())
    assert index["torrents"][0]["file_id"] == torrent["file_id"]
    shared = DIRECT.open(f"{base}/share/{torrent['file_id']}.torrent.json").read()
    assert json.loads(shared)["file_sha256"] == torrent["file_sha256"]
    for headers in ({"X-BTL-GUI": "0"}, {"Host": "evil.example"}):
        with pytest.raises(urllib.error.HTTPError) as error:
            call(base, "/api/tracker/start", {}, headers=headers)
        assert error.value.code == 403


def test_join_another_gui_fetches_torrent_and_tracker(gui, tmp_path, monkeypatch):
    host, host_base = gui
    source = tmp_path / "c.bin"
    source.write_bytes(b"z" * 7000)
    call(host_base, "/api/tracker/start", {})
    file_id = call(host_base, "/api/torrents/create", {"source": str(source)})["torrent"]["file_id"]

    monkeypatch.setattr("bittorrent_lite.gui.app.DEFAULT_GUI_PORT", host.gui_port)
    laptop = GuiApp(tmp_path / "laptop", netinfo.next_free_port(host.gui_port + 1), share=False)
    joined = laptop.join("127.0.0.1")
    assert joined["tracker"] == f"http://127.0.0.1:{host.settings['tracker_port']}"
    assert joined["tracker_check"]["ok"]
    assert [t["file_id"] for t in joined["torrents"]] == [file_id]
    fetched = laptop.fetch_shared("127.0.0.1", file_id)
    assert fetched["torrent"]["file_id"] == file_id
    assert laptop.tracker_url() == joined["tracker"]
    with pytest.raises(Exception, match="this computer's own GUI"):
        host.join("127.0.0.1")


def test_own_address_as_tracker_means_local_and_peers_start_it(gui, tmp_path):
    app, base = gui
    own = app.settings["advertise_ip"]
    port = app.settings["tracker_port"]
    state = call(base, "/api/settings", {"tracker_url": f"{own}:{port}"})
    assert not state["tracker_custom"]
    assert state["tracker_url"] == f"http://{own}:{port}"
    source = tmp_path / "d.bin"
    source.write_bytes(b"w" * 3000)
    file_id = call(base, "/api/torrents/create", {"source": str(source)})["torrent"]["file_id"]
    state = call(base, "/api/peers/start", {"file_id": file_id, "role": "seeder"})
    assert state["tracker"]["running"]          # started for the seeder, not left to the person
    assert app.probe_tracker(state["tracker_url"])["ok"]

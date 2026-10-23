# Browser GUI

`python -m bittorrent_lite.gui` opens a browser page that does everything the
three-terminal demo does: start a tracker, create a torrent, seed it, let other
laptops download it, and show live progress with an automatic hash check. It
also runs the experiment matrix and shows its figures.

The GUI adds no dependencies (Python standard library only) and changes no
backend code. It starts the existing programs as child processes, with the
same interpreter, and reads their output:

| Program | Started for |
|---|---|
| `python -m bittorrent_lite.discovery.tracker_server --host 0.0.0.0` | Start tracker here |
| `python -m bittorrent_lite.storage.generate_metadata` | Create torrent |
| `python -m bittorrent_lite --check-config ...` | The check shown in Add peer before anything starts |
| `python -m bittorrent_lite ... --stop-file <file>` | Every peer; Stop creates the file |
| `python -m bittorrent_lite.experiments.scripts.make_fixture`, `matrix`, `plot` | Experiments |

## Running it

Mac, Windows and Linux, Python 3.10 or newer, from the repository folder:

```bash
python -m pip install -e .          # once; the GUI then also runs from any folder
python -m bittorrent_lite.gui       # opens http://127.0.0.1:8765
```

Options: `--port 8766` for a second copy on one machine, `--workdir PATH`
(default `~/BitTorrentLite`), `--no-browser`, `--no-share`. Ctrl+C in the
terminal stops the GUI and, first, its peers and tracker.

The Experiments page also needs `python -m pip install -e ".[experiments]"`.

## Two or more laptops (Tailscale or one Wi-Fi)

1. Every laptop: open the GUI. The sidebar shows "This computer" with the
   address others should use; a Tailscale address (100.x.y.z) is picked first.
2. Sharing laptop: Create torrent, choose the file, Create, then Seed this file
   now. This starts the tracker on the laptop and a seeder.
3. Every other laptop: Join swarm, type the sharing laptop's address, click
   Download next to the file, then Start downloader.
4. Each downloader turns "Done, seeding" with a tick when its file's SHA-256
   matches the torrent. Stop it when you are finished.

On Windows, allow Python through the firewall the first time Windows asks
(once for the GUI, once for the peers).

## What it fixes from the 23 Oct cross-city test

| Problem | What the GUI does |
|---|---|
| Wrong `--host` address gave Errno 49 | Peers always listen on `0.0.0.0`. The chosen address is used only in the tracker URL, so the tracker records a reachable IP instead of 127.0.0.1. |
| Two peers with one `--peer-id` stall silently | IDs are generated as `<computer>-<4 hex>`; a duplicate of a running peer or of a peer the tracker knows is refused. Ports are the next free ones. |
| Remembering the tracker address | Saved in `<workdir>/.gui/settings.json`; Join swarm fills it in; Network settings has a Test button. |
| Copying metadata with curl or Invoke-WebRequest | The sharing GUI serves its torrents read-only at `/share/`; Join swarm downloads them. Upload and download buttons cover other cases. |
| Checking the final hash by hand | On COMPLETE the GUI hashes the output file and compares it with `file_sha256` from the torrent. |
| SEEDING after COMPLETE looked like a problem | Shown as "Done, seeding" with a note that a finished peer keeps uploading until stopped. |

## Design notes

- `gui/server.py`: `ThreadingHTTPServer`. The JSON API answers only requests
  from a loopback address with a local `Host` header and an `X-BTL-GUI: 1`
  header, so other machines and other web pages cannot drive it. Other
  machines can reach only `GET /share/index.json` and
  `GET /share/<file_id>.torrent.json`.
- `gui/processes.py`: one reader thread per child parses the JSON event lines
  (`START`, `STATUS`, `PIECE_VERIFIED`, `PROGRESS`, `COMPLETE`, `CONNECTED`,
  `SCHEDULER_SNAPSHOT`, `STOPPED`) into the peer model. The piece map comes from
  `PIECE_VERIFIED` (verified) and the scheduler snapshot's pending list
  (requested); a restarted peer starts from the `.piece` files already on disk.
  Rates are the change in `STATUS` byte counters over the last few seconds.
  The tracker's log lines give the "Seen by the tracker" list, which includes
  peers on other computers.
- `gui/app.py`: settings, torrents, peer start/stop/restart, joining, experiments.
- `gui/static/`: the page (plain HTML, CSS and JavaScript, no build step). It
  polls `/api/state` once a second and patches the DOM in place.
- Torrents with pieces over 64 KiB are flagged: the network backend refuses them.
- Experiments use tracker port 18000 and peer ports from 17001 so they do not
  collide with a tracker the GUI is running on 8000.

Tests: `python -m pytest bittorrent_lite/tests/gui` (address and ID helpers,
a real seed/download/restart through the HTTP API, duplicate-ID refusal, the
share endpoint's access rules, and joining one GUI from another).

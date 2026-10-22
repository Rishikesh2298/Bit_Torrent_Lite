"""Phase 04 diagnostic integration: genuine guarded 1S/1L localhost transfer.

Always execute the swarm in an owned RecordingSession child, even when pytest
itself has an outer recorder. The child's total command timeout is 65 seconds;
all internal waits are finite. No mocks, synthetic event files, source-isolation
claim, measured-matrix credit, or external-verifier claim is made here.

Authoring this file did not execute it. Run through the root's sequential
diagnostic recorder while source edits are paused. Keep every failed run root,
raw stream, command record and failure traceback for diagnosis.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import traceback

from bittorrent_lite.acceptance_tools import measured
from bittorrent_lite.acceptance_tools.evidence import compare_files, strict_json, verify_metadata
from bittorrent_lite.acceptance_tools.inventory import compare_snapshots, snapshot, write_json_new
from bittorrent_lite.acceptance_tools.recording import RecordingSession, matching_process
from bittorrent_lite.experiments.scripts.launcher import DEFAULTS
from bittorrent_lite.storage.metadata import create_metadata, save_metadata


def _current_commit(repo):
    """Read actual HEAD without executing Git or taking a caller-supplied SHA."""
    git = repo / ".git"
    if git.is_file():
        pointer = git.read_text(encoding="utf-8").strip()
        if not pointer.startswith("gitdir: "):
            raise ValueError("invalid actual Git directory pointer")
        git = (repo / pointer[8:]).resolve(strict=True)
    common = git
    if (git / "commondir").is_file():
        common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve(strict=True)
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        reference = head[5:]
        if not reference.startswith("refs/") or any(part in {"", ".", ".."} for part in reference.split("/")):
            raise ValueError("invalid actual Git reference")
        loose = common / reference
        if loose.is_file():
            head = loose.read_text(encoding="utf-8").strip()
        else:
            candidates = [line.split(" ", 1)[0]
                          for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines()
                          if not line.startswith(("#", "^")) and line.endswith(" " + reference)]
            if len(candidates) != 1:
                raise ValueError("actual Git reference is not uniquely resolved")
            head = candidates[0]
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("actual Git commit is not a SHA-1 object identity")
    return head


def _independent_source(path):
    """Fresh distinct binary pieces generated and hashed using only stdlib."""
    seed = os.urandom(32)
    piece_size = 65536
    size = 16 * piece_size + 137
    whole = hashlib.sha256()
    pieces = []
    with path.open("xb") as stream:
        for index, offset in enumerate(range(0, size, piece_size)):
            length = min(piece_size, size - offset)
            data = bytearray(hashlib.shake_256(seed + index.to_bytes(8, "big")).digest(length))
            data[:10] = index.to_bytes(8, "big") + b"\x00\xff"
            data[-8:] = (2**64 - index - 1).to_bytes(8, "big")
            raw = bytes(data)
            stream.write(raw)
            whole.update(raw)
            pieces.append({"index": index, "size": length, "sha256": hashlib.sha256(raw).hexdigest()})
    if len({piece["sha256"] for piece in pieces}) != len(pieces):
        raise AssertionError("diagnostic fixture pieces unexpectedly duplicate")
    return {"size": size, "piece_size": piece_size, "sha256": whole.hexdigest(), "pieces": pieces}, hashlib.sha256(seed).hexdigest()


def _bind_owned_ports():
    """Probe and temporarily reserve two consecutive peer ports plus tracker."""
    last_error = None
    for _ in range(32):
        held = []
        try:
            for _ in range(3):
                stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if os.name == "nt":
                    stream.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                held.append(stream)
            held[0].bind(("127.0.0.1", 0))
            base = held[0].getsockname()[1]
            if base >= 65535:
                raise OSError("no consecutive port after ephemeral upper boundary")
            held[1].bind(("127.0.0.1", base + 1))
            held[2].bind(("127.0.0.1", 0))
            return held, base, held[2].getsockname()[1]
        except OSError as exc:
            last_error = exc
            for stream in held:
                stream.close()
    raise OSError("could not reserve diagnostic loopback ports within 32 attempts") from last_error


def _worker(root):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    run = None
    try:
        registry_value = os.environ.get("ACCEPTANCE_PROCESS_REGISTRY")
        if not registry_value:
            raise RuntimeError("lifecycle worker requires its enclosing RecordingSession registry")
        registry = Path(registry_value).resolve(strict=True)
        guardians = [strict_json(line) for line in (registry.parent / "guardian.jsonl").read_bytes().splitlines()]
        if (not guardians or guardians[0].get("action") != "guardian_ready"
                or matching_process(guardians[0]["identity"]) is None):
            raise RuntimeError("independent command guardian is not alive")
        source = root / "diagnostic-source.bin"
        independent, seed_digest = _independent_source(source)
        metadata = root / "diagnostic-source.torrent.json"
        save_metadata(create_metadata(str(source), 65536), str(metadata))
        checked = verify_metadata(source, metadata)
        if {key: checked[key] for key in independent} != independent:
            raise AssertionError("project metadata differs from independent stdlib source oracle")
        before = snapshot(measured.REPO_ROOT)
        revision = _current_commit(measured.REPO_ROOT)
        write_json_new(root / "source-snapshot-before.json", before)
        write_json_new(root / "fixture-oracle.json", {"lane": "diagnostic", "generator": "stdlib-os-random-shake256-index-v1",
            "seed_sha256": seed_digest, "oracle": independent, "metadata_sha256": checked["metadata_sha256"],
            "source_freeze": before["sha256"], "external_challenge": False})
        config = copy.deepcopy(DEFAULTS)
        config.update(name="guarded-lifecycle-diagnostic", L=1, S=1, repeat=1, seed=113,
                      fixture=str(source), metadata=str(metadata), piece_bytes=65536, window=4,
                      scenario="baseline", synthetic=False, timeout_s=35, ready_timeout_s=6, launch_gap_s=0.2)
        config["peer_command"] = [*config["peer_command"], "--host", "127.0.0.1", "--resource-metrics",
                                  "--upload-workers", "0", "--shutdown-timeout", "4"]
        ports, base, tracker = _bind_owned_ports()
        try:
            config.update(base_port=base, tracker_port=tracker)
            write_json_new(root / "port-reservations.json", {"host": "127.0.0.1", "observed_mono": time.monotonic(),
                "tracker_port": tracker, "peer_ports": [base, base + 1], "method": "actual-owned-bind-before-release"})
            write_json_new(root / "config.json", config)
            run = measured.GuardedRun(config, root / "runs", source_freeze=before["sha256"],
                                      revision=revision, registry=registry, lane="diagnostic")
        finally:
            for stream in ports:
                stream.close()
        write_json_new(root / "ports-released.json", {"released_mono": time.monotonic(),
            "note": "Release precedes Run preflight and real child binds; any intervening collision must fail."})
        manifest = run.execute()
        result = measured.verify_run(run.dir, config, source_freeze=before["sha256"],
                                     revision=revision, lane="diagnostic")
        if manifest["status"] != "ok" or result["status"] != "VERIFIED":
            raise AssertionError("real guarded lifecycle did not pass strict semantics")
        output = run.dir / "peers" / "peer-01" / source.name
        compare_files(source, output, independent)
        if source.read_bytes() != output.read_bytes():
            raise AssertionError("independent full-byte comparison failed")
        if (result["expected_complete"] != ["peer-01"]
                or set(result["peer_completion_s"]) != {"peer-01"}
                or result["metrics"]["seed-01"]["verified_download_bytes"] != 0
                or result["metrics"]["seed-01"]["requests_sent"] != 0
                or result["metrics"]["peer-01"]["verified_download_bytes"] != independent["size"]
                or result["metrics"]["seed-01"]["uploaded_payload_bytes"] < independent["size"]
                or result["metrics"]["peer-01"]["requests_sent"] < len(independent["pieces"])):
            raise AssertionError("actual transfer population or payload arithmetic differs")
        seed_events = [json.loads(line) for line in (run.dir / "events" / "seed-01.jsonl").read_text(encoding="utf-8").splitlines()]
        seed_ready = [item for item in seed_events if item["event"] == "complete"]
        if len(seed_ready) != 1 or seed_ready[0]["final_hash_ok"] is not True:
            raise AssertionError("actual initial seeder lacks exactly one verified source-ready assembly")
        compare_files(source, run.dir / "peers" / "seed-01" / source.name, independent)
        after = snapshot(measured.REPO_ROOT)
        write_json_new(root / "source-snapshot-after.json", after)
        compare_snapshots(before, after)
        write_json_new(run.dir / "semantic-verification.json", result)
        write_json_new(root / "diagnostic-result.json", {"status": "VERIFIED", "lane": "diagnostic",
            "source_isolation_claimed": False, "acceptance_credit": False, "external_verifier_claimed": False,
            "run_dir": str(run.dir), "source_freeze": before["sha256"], "revision": revision,
            "config": config, "result": result})
    except BaseException:
        # Raw traceback is retained in addition to recorder stdout/stderr. Never
        # replace a verifier exception with a fabricated status or weaker oracle.
        (root / "failure-traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        write_json_new(root / "diagnostic-failure.json", {"status": "FAILED", "lane": "diagnostic",
            "run_dir": str(run.dir) if run else None, "acceptance_credit": False})
        raise


def test_real_guarded_localhost_lifecycle_has_strict_process_and_transfer_evidence(tmp_path):
    before = snapshot(measured.REPO_ROOT)
    recorder = RecordingSession(tmp_path / "command-records", "preparation", "measured-lifecycle",
                                {"source": before["sha256"]})
    root = tmp_path / "real-lifecycle"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(measured.REPO_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONUNBUFFERED"] = "1"
    for key in ("BTL_EVENT_LOG", "BTL_PROC_ID", "BTL_RUN_ID", "BTL_LOG_STRICT"):
        environment.pop(key, None)
    record = recorder.run("real-1s1l", [sys.executable, str(Path(__file__).resolve()), "--worker", str(root)],
                          cwd=measured.REPO_ROOT, env=environment, timeout_s=65,
                          expected_exit_codes=(0,),
                          oracle="diagnostic: genuine guarded 1S/1L transfer; strict OS identity/sequence/PID, metadata, bytes, metrics and owned cleanup; no acceptance/source-isolation credit")
    assert record["status"] == "PASS" and record["exit_code"] == 0
    assert record["timed_out"] is False and record["cleanup_errors"] == []
    data = strict_json((root / "diagnostic-result.json").read_bytes())
    assert data["status"] == "VERIFIED" and data["lane"] == "diagnostic"
    assert data["source_isolation_claimed"] is False and data["acceptance_credit"] is False
    assert data["external_verifier_claimed"] is False
    compare_snapshots(before, strict_json((root / "source-snapshot-before.json").read_bytes()))
    compare_snapshots(before, strict_json((root / "source-snapshot-after.json").read_bytes()))
    compare_snapshots(before, snapshot(measured.REPO_ROOT))
    # Recompute in the parent process after the recorded worker and its children
    # have exited. This is a second mechanical check, not an external reviewer.
    verified = measured.verify_run(Path(data["run_dir"]), data["config"], source_freeze=data["source_freeze"],
                                   revision=data["revision"], lane="diagnostic")
    assert verified == data["result"]
    write_json_new(root / "parent-semantic-verification.json", verified)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    _worker(parser.parse_args().worker)

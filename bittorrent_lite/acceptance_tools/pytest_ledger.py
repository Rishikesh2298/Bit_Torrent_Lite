"""Fail-closed pytest collection/outcome ledger, loaded explicitly with ``-p``.

Required option: --acceptance-ledger=<absent-directory>. Optional
--acceptance-expected-nodes=<JSON-array> compares exact identities before bodies
execute. Use a full collection first; reviewed phase partitions must reconcile
outside this plugin. JUnit remains pytest's own output, with each node ID added
as a testcase property so another verifier need not guess name transformations.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import time

import pytest


def _write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_expected(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("expected nodes must be a nonempty JSON list")
    if any(not isinstance(n, str) or not n.strip() or n != n.strip() for n in value):
        raise ValueError("expected node IDs must be nonblank exact strings")
    if len(value) != len(set(value)):
        raise ValueError("duplicate expected node IDs")
    return value


def reconcile(nodeids, reports, *, collect_only=False):
    """Pure exact-identity/three-phase oracle, also tested with negative controls."""
    problems = []
    if not nodeids:
        problems.append("empty collection")
    if len(nodeids) != len(set(nodeids)):
        problems.append("duplicate collected node IDs")
    if collect_only:
        if reports:
            problems.append("collect-only invocation executed test phases")
        return problems
    expected = {(node, phase) for node in nodeids for phase in ("setup", "call", "teardown")}
    seen = Counter((r["nodeid"], r["when"]) for r in reports)
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    if missing:
        problems.append(f"missing outcomes: {missing}")
    if extra:
        problems.append(f"uncollected outcomes: {extra}")
    duplicates = sorted(key for key, count in seen.items() if count != 1)
    if duplicates:
        problems.append(f"duplicate outcomes: {duplicates}")
    for report in reports:
        if report["outcome"] != "passed" or report.get("wasxfail"):
            problems.append(f"nonpassing outcome: {report['nodeid']} {report['when']} "
                            f"{report['outcome']} xfail={report.get('wasxfail')!r}")
    return problems


class Ledger:
    def __init__(self, config):
        target = config.getoption("acceptance_ledger")
        if not target:
            raise pytest.UsageError("acceptance ledger plugin requires --acceptance-ledger")
        self.root = Path(target).absolute()
        for part in (self.root, *self.root.parents):
            try:
                reparse = getattr(part.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            except FileNotFoundError:
                reparse = False
            if reparse or part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise pytest.UsageError(f"redirected ledger path: {part}")
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.reports = []
        self.collection = []
        self.problems = []
        self.session = None
        self.expected = None
        expected_path = config.getoption("acceptance_expected_nodes")
        if expected_path:
            self.expected = load_expected(expected_path)
        # This makes the stop requirement explicit for every invocation, including
        # invocations where a caller accidentally omitted -x.
        config.option.maxfail = 1
        self.config = config
        _write_new(self.root / "invocation.json", {
            "schema": "btl-pytest-ledger-v1", "args": list(config.invocation_params.args),
            "rootpath": str(config.rootpath), "inipath": str(config.inipath),
            "pid": os.getpid(), "collection_only": config.option.collectonly,
            "expected_nodeids": self.expected,
            "environment": {key: os.environ.get(key) for key in
                            ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONPATH")},
            "warning_filters": list(config.getini("filterwarnings")),
        })

    def _event(self, value):
        value = {"recorded_mono": time.monotonic(), **value}
        with (self.root / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def pytest_sessionstart(self, session):
        self.session = session

    def pytest_deselected(self, items):
        ids = [item.nodeid for item in items]
        self.problems.append(f"deselected nodes: {ids}")
        self._event({"kind": "deselected", "nodeids": ids})

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session):
        for item in session.items:
            markers = sorted(marker.name for marker in item.iter_markers())
            path = Path(item.path)
            self.collection.append({"nodeid": item.nodeid, "markers": markers,
                                    "source": str(path), "line": item.location[1] + 1,
                                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            item.user_properties.append(("acceptance_nodeid", item.nodeid))
            if any(marker in markers for marker in ("skip", "skipif", "xfail")):
                self.problems.append(f"prohibited conditional/skip/xfail marker: {item.nodeid}")
        nodeids = [row["nodeid"] for row in self.collection]
        if not nodeids:
            self.problems.append("empty collection")
        if len(nodeids) != len(set(nodeids)):
            self.problems.append("duplicate collected node IDs")
        if self.expected is not None and set(nodeids) != set(self.expected):
            self.problems.append(f"collection differs: missing={sorted(set(self.expected) - set(nodeids))}; "
                                 f"extra={sorted(set(nodeids) - set(self.expected))}")
        _write_new(self.root / "collection.json", {"cases": self.collection, "problems": self.problems})
        if self.problems:
            session.shouldstop = "acceptance collection ledger rejected the invocation"
            raise pytest.UsageError("; ".join(self.problems))

    def pytest_collectreport(self, report):
        if report.failed or report.skipped:
            self.problems.append(f"collection {report.outcome}: {report.nodeid}")
        self._event({"kind": "collection_outcome", "nodeid": report.nodeid,
                     "outcome": report.outcome, "longrepr": str(report.longrepr) if report.longrepr else None})

    def pytest_runtest_logreport(self, report):
        row = {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
               "duration": report.duration, "start": report.start, "stop": report.stop,
               "wasxfail": getattr(report, "wasxfail", None),
               "longrepr": str(report.longrepr) if report.longrepr else None}
        self.reports.append(row)
        self._event({"kind": "test_outcome", **row})
        if report.failed or report.skipped or getattr(report, "wasxfail", None):
            self.problems.append(f"prohibited/nonpassing {report.outcome}: {report.nodeid} {report.when}")
            self.session.shouldstop = "first nonpassing acceptance outcome"

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        nodeids = [row["nodeid"] for row in self.collection]
        self.problems.extend(reconcile(nodeids, self.reports, collect_only=self.config.option.collectonly))
        if exitstatus != 0:
            self.problems.append(f"pytest exit status {int(exitstatus)}")
        if self.problems and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        _write_new(self.root / "outcomes.json", {
            "schema": "btl-pytest-ledger-v1", "collection": nodeids, "reports": self.reports,
            "problems": self.problems, "pytest_exit_status": int(session.exitstatus),
            "status": "FAIL" if self.problems else "PASS",
            "scope": "collection only" if self.config.option.collectonly else "collection and terminal outcomes",
        })


def pytest_addoption(parser):
    group = parser.getgroup("acceptance-ledger")
    group.addoption("--acceptance-ledger", help="Fresh directory for exact collection and outcomes")
    group.addoption("--acceptance-expected-nodes", help="JSON array of exact expected node IDs")


def pytest_configure(config):
    try:
        plugin = Ledger(config)
    except (ValueError, OSError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    config.pluginmanager.register(plugin, "acceptance-outcome-ledger")

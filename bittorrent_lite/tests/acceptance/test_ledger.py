"""Exact-identity and terminal-outcome negative controls for the pytest ledger."""

import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

from bittorrent_lite.acceptance_tools.pytest_ledger import load_expected, reconcile
from bittorrent_lite.acceptance_tools.recording import RecordingSession


def outcomes(node="test_a.py::test_ok"):
    return [{"nodeid": node, "when": phase, "outcome": "passed", "wasxfail": None}
            for phase in ("setup", "call", "teardown")]


def test_exact_three_phase_identity_set_passes():
    assert reconcile(["test_a.py::test_ok"], outcomes()) == []


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_missing_phase_rejected(phase):
    assert any("missing outcomes" in p for p in reconcile(
        ["test_a.py::test_ok"], [r for r in outcomes() if r["when"] != phase]))


def test_equal_count_different_identity_rejected():
    problems = reconcile(["test_a.py::test_ok"], outcomes("test_b.py::test_other"))
    assert any("missing outcomes" in p for p in problems)
    assert any("uncollected outcomes" in p for p in problems)


def test_duplicate_outcomes_and_collection_rejected():
    problems = reconcile(["test_a.py::test_ok"] * 2, outcomes() + outcomes())
    assert any("duplicate collected" in p for p in problems)
    assert any("duplicate outcomes" in p for p in problems)


@pytest.mark.parametrize("outcome,xfail", [("skipped", None), ("failed", None),
                                          ("skipped", "expected fail"), ("passed", "unexpected pass")])
def test_skip_fail_xfail_xpass_rejected(outcome, xfail):
    reports = outcomes()
    reports[1].update(outcome=outcome, wasxfail=xfail)
    assert any("nonpassing" in p for p in reconcile(["test_a.py::test_ok"], reports))


def test_empty_collection_never_passes():
    assert reconcile([], []) == ["empty collection"]
    assert reconcile([], [], collect_only=True) == ["empty collection"]


def test_collect_only_requires_no_test_execution():
    assert reconcile(["test_a.py::test_ok"], [], collect_only=True) == []
    assert reconcile(["test_a.py::test_ok"], outcomes(), collect_only=True)


@pytest.mark.parametrize("value", [[], [""], [" "], [" x"], ["x", "x"], {}, [1]])
def test_invalid_selector_lists_rejected(tmp_path, value):
    path = tmp_path / "nodes.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_expected(path)


def test_parameterized_identities_remain_distinct(tmp_path):
    expected = ["test_a.py::test_values[1]", "test_a.py::test_values[2]"]
    path = tmp_path / "nodes.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert load_expected(path) == expected
    assert reconcile(expected, outcomes(expected[0]) + outcomes(expected[1])) == []


def _invoke_fixture(tmp_path, source, expected_exit):
    fixture = tmp_path / "isolated pytest"
    fixture.mkdir()
    (fixture / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (fixture / "test_fixture.py").write_text(source, encoding="utf-8")
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # This explicitly tests hook integration, not installed-package portability.
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    recorder = RecordingSession(tmp_path / "records", "diagnostic", "pytest-plugin", {})
    ledger, junit = fixture / "ledger", fixture / "junit.xml"
    result = recorder.run("nested-pytest", [sys.executable, "-m", "pytest", "-q", "-x",
        "-p", "bittorrent_lite.acceptance_tools.pytest_ledger", "--acceptance-ledger", str(ledger),
        "--junitxml", str(junit), "test_fixture.py"], cwd=fixture, env=environment,
        timeout_s=20, expected_exit_codes=(expected_exit,),
        oracle="predeclared plugin fixture: exact terminal ledger and pytest-generated XML")
    return fixture, ledger, junit, result


def test_real_pytest_plugin_reconciles_parameterized_xml_identities(tmp_path):
    _, ledger, junit, result = _invoke_fixture(tmp_path,
        "import pytest\n@pytest.mark.parametrize('n', [1, 2])\ndef test_number(n):\n    assert n > 0\n", 0)
    expected = {"test_fixture.py::test_number[1]", "test_fixture.py::test_number[2]"}
    report = json.loads((ledger / "outcomes.json").read_text())
    assert report["problems"] == []
    assert set(report["collection"]) == expected
    assert len(report["reports"]) == 6
    cases = ET.parse(junit).findall(".//testcase")
    xml_nodes = [case.find("./properties/property[@name='acceptance_nodeid']").attrib["value"]
                 for case in cases]
    assert len(xml_nodes) == len(set(xml_nodes)) == 2
    assert set(xml_nodes) == expected
    assert result["exit_code"] == 0


def test_real_pytest_dynamic_skip_fails_before_next_body(tmp_path):
    fixture, ledger, _, result = _invoke_fixture(tmp_path,
        "import pytest\nfrom pathlib import Path\n"
        "def test_a_skip():\n    pytest.skip('negative control')\n"
        "def test_b_must_not_run():\n    Path('later-body-ran').write_text('bad')\n", 2)
    report = json.loads((ledger / "outcomes.json").read_text())
    assert report["status"] == "FAIL"
    assert any("skipped" in p for p in report["problems"])
    assert any("missing outcomes" in p for p in report["problems"])
    assert not (fixture / "later-body-ran").exists()
    assert result["exit_code"] == 2

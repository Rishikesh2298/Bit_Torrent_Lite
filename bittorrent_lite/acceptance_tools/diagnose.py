"""Run a finite preparation command with genuine records, never acceptance credit."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .inventory import snapshot, write_json_new
from .recording import RecordingFailure, RecordingSession


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--oracle', required=True)
    parser.add_argument('--expected-exit', type=int, action='append')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    before = snapshot(args.repo)
    recorder = RecordingSession(args.out, 'preparation', args.out.name,
                                {'source_at_start': before['sha256']})
    write_json_new(recorder.root / 'source-at-start.json', before)
    write_json_new(recorder.root / 'lane.json', {
        'lane': 'PREPARATION DIAGNOSTIC', 'acceptance_credit': False,
        'source_frozen': False,
        'limitation': 'Preparation may still change concurrently; hashes identify observed files only.'})
    environment = dict(os.environ)
    environment.pop('PYTEST_ADDOPTS', None)
    environment.pop('PYTEST_PLUGINS', None)
    try:
        record = recorder.run('command', command, cwd=args.cwd,
            env=environment, timeout_s=args.timeout,
            expected_exit_codes=tuple(args.expected_exit or [0]), oracle=args.oracle)
    except RecordingFailure as exc:
        print(json.dumps({'record': str(recorder.root / 'command/record.json'),
                          'status': 'FAIL', 'acceptance_credit': False,
                          'exception': exc.record['exception'],
                          'cleanup_errors': exc.record['cleanup_errors']}))
        return 1
    finally:
        write_json_new(recorder.root / 'source-at-end.json', snapshot(args.repo))
    print(json.dumps({'record': str(recorder.root / 'command/record.json'),
                      'status': record['status'], 'exit_code': record['exit_code'],
                      'acceptance_credit': False,
                      'semantic_oracle_status': record['semantic_oracle_status']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

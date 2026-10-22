"""Record finite preparation commands before the full guardian is available.

This bootstrap deliberately refuses acceptance credit. Use recording.py for
the campaign and process trees; this runner only owns its direct finite child.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or args.timeout <= 0:
        parser.error('command and positive timeout required')
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc)
    monotonic = time.monotonic()
    record = {'lane': 'PREPARATION DIAGNOSTIC—NO ACCEPTANCE CREDIT',
              'argv': command, 'cwd': str(args.cwd.resolve(strict=True)),
              'started_utc': started.isoformat(),
              'started_local': started.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat(),
              'timeout_s': args.timeout, 'pid': None, 'exit_code': None,
              'timed_out': False,
              'environment': {k: v for k, v in os.environ.items()
                              if k in {'PATH', 'PYTHONPATH', 'PYTEST_ADDOPTS', 'TEMP', 'TMP',
                                       'VIRTUAL_ENV', 'COVERAGE_PROCESS_START', 'COVERAGE_FILE'}}}
    try:
        with (root / 'stdout.bin').open('xb') as out, (root / 'stderr.bin').open('xb') as err:
            child = subprocess.Popen(command, cwd=args.cwd, stdout=out, stderr=err,
                                     stdin=subprocess.DEVNULL, shell=False)
            record['pid'] = child.pid
            (root / 'started.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            try:
                record['exit_code'] = child.wait(args.timeout)
            except subprocess.TimeoutExpired:
                record['timed_out'] = True
                child.terminate()
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(5)
                record['exit_code'] = child.returncode
    except BaseException:
        record['exception'] = traceback.format_exc()
        raise
    finally:
        record['ended_utc'] = datetime.now(timezone.utc).isoformat()
        record['elapsed_monotonic_s'] = time.monotonic() - monotonic
        record['artifacts'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                               for name in ('stdout.bin', 'stderr.bin') if (root / name).exists()}
        (root / 'record.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record))
    return 1 if record['timed_out'] else record['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())

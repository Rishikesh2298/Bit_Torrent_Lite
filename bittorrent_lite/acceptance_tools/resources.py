"""Actual local resource observations for opt-in acceptance instrumentation."""
from __future__ import annotations

import os
import argparse
import json
from pathlib import Path
import platform
import shutil
import sys


def process_sample():
    import psutil
    process = psutil.Process()
    cpu = process.cpu_times()
    metrics = {'rss_bytes': process.memory_info().rss,
               'thread_count': process.num_threads(),
               'tcp_socket_count': len(process.net_connections(kind='tcp')),
               'cpu_user_s': cpu.user, 'cpu_system_s': cpu.system}
    if os.name == 'nt':
        metrics['handle_count'] = process.num_handles()
    else:
        metrics['file_descriptor_count'] = process.num_fds()
    return metrics


def host_inventory(path: Path):
    import psutil
    disk = shutil.disk_usage(path)
    memory = psutil.virtual_memory()
    return {'platform': platform.platform(), 'machine': platform.machine(),
            'python': platform.python_version(), 'executable': sys.executable,
            'logical_cpu_count': psutil.cpu_count(), 'ram_total_bytes': memory.total,
            'ram_available_bytes': memory.available,
            'disk_total_bytes': disk.total, 'disk_free_bytes': disk.free,
            'disk_path': str(path.resolve()),
            'process': process_sample(),
            'limitations': ['Current observations are not resource reservations.',
                            'No claim about teammate or professor hardware.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(host_inventory(args.path), allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

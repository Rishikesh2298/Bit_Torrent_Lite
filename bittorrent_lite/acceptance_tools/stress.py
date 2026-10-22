"""Finite real-process diagnostic stress preparation, with acceptance blocked.

The local workload uses real project peers, tracker, sockets and fresh downloads.
It is deliberately labelled diagnostic: its source remains readable to the same
OS user. This is not a source-isolation adapter or a killed-peer final observer.
No shortened duration/cycle mode and no arbitrary shell/command injection exist.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import time
import traceback

from .evidence import strict_json
from .inventory import canonical_bytes, checked_path, compare_snapshots, digest_file, snapshot, write_json_new


class StressBlocked(RuntimeError):
    pass


GRID = tuple(itertools.product((1, 2), (6, 8), (0, 2), (1, 4)))
FIXTURE_BYTES = 64 * 1024 * 1024
GAUGES = ('rss_bytes', 'thread_count', 'tcp_socket_count', 'descriptor_count')
LIMIT_KEYS = {'peer_max', 'settled_growth', 'supervisor_growth', 'active_jobs',
              'neighbor_records', 'sample_gap_s', 'busy_freshness_s',
              'settle_s', 'start_timeout_s', 'cleanup_timeout_s',
              'disk_headroom_bytes', 'raw_log_budget_bytes', 'ram_headroom_bytes',
              'pilot_evidence'}


def _finite(value, label, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'invalid {label}')
    return value


def _hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_limits(limits, *, pilot=False):
    if not isinstance(limits, dict) or set(limits) != LIMIT_KEYS:
        raise StressBlocked('all reviewed resource/time limits and pilot evidence are required')
    for group in ('peer_max', 'settled_growth', 'supervisor_growth'):
        if not isinstance(limits[group], dict) or set(limits[group]) != set(GAUGES):
            raise ValueError(f'exact resource gauges required for {group}')
        for key, value in limits[group].items():
            if type(value) is not int or value < (1 if group == 'peer_max' else 0):
                raise ValueError(f'invalid integer resource limit: {group}/{key}')
    for key in ('active_jobs', 'neighbor_records', 'disk_headroom_bytes',
                'raw_log_budget_bytes', 'ram_headroom_bytes'):
        if type(limits[key]) is not int or limits[key] <= 0:
            raise ValueError(f'positive reviewed integer required: {key}')
    for key in ('sample_gap_s', 'busy_freshness_s', 'settle_s', 'start_timeout_s', 'cleanup_timeout_s'):
        _finite(limits[key], key, .001)
    if limits['sample_gap_s'] > 3 or limits['busy_freshness_s'] > 1 or limits['settle_s'] < 2:
        raise ValueError('resource gap <=3s, busy observation age <=1s and settling >=2s required')
    ref = limits['pilot_evidence']
    if pilot and ref is None:
        return
    if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
            or not isinstance(ref['path'], str) or not ref['path']
            or Path(ref['path']).is_absolute() or '..' in Path(ref['path']).parts
            or not isinstance(ref['sha256'], str) or len(ref['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in ref['sha256'])):
        raise StressBlocked('relative hashed pilot evidence for reviewed limits is required')


def make_plan(*, source_freeze, limits, duration_s=1800, cycles=100, seed=2026, lane='diagnostic'):
    validate_limits(limits)
    if type(cycles) is not int or cycles < 100 or type(seed) is not int or seed < 0:
        raise ValueError('at least 100 cycles and a nonnegative deterministic seed are required')
    _finite(duration_s, 'duration', 1800)
    if duration_s / cycles <= limits['settle_s']:
        raise ValueError('cycle slots must contain positive work time before settling')
    cases = []
    for index, (seeders, downloaders, workers, window) in enumerate(GRID):
        rng = random.Random(seed + index)
        case_id = f'S{seeders}-L{downloaders}-W{workers}-Q{window}'
        cases.append({'case_id': case_id, 'seeders': seeders, 'downloaders': downloaders,
                      'upload_workers': workers, 'window': window, 'fixture_seed': seed + index,
                      'churn': [{'cycle': n + 1, 'slot': rng.randrange(downloaders),
                                 'at_s': n * duration_s / cycles,
                                 'deadline_s': (n + 1) * duration_s / cycles}
                                for n in range(cycles)]})
    plan = {'schema': 'btl-stress-plan-v1', 'lane': lane, 'source_freeze': source_freeze,
            'duration_s': duration_s, 'cycles': cycles, 'seed': seed,
            'fixture_bytes': FIXTURE_BYTES, 'limits': limits, 'cases': cases}
    plan['sha256'] = _hash(plan)
    validate_plan(plan)
    return plan


def make_pilot_plan(*, source_freeze, limits):
    """Fixed 60-second, one-cycle PREPARE diagnostic, never a stress-grid case."""
    validate_limits(limits, pilot=True)
    if limits['settle_s'] >= 20 or limits['start_timeout_s'] > 45 or limits['cleanup_timeout_s'] > 15:
        raise ValueError('pilot requires settling <20s, startup <=45s and cleanup <=15s (total <=120s)')
    case = {'case_id': 'PREPARE-PILOT-S1-L6-W2-Q4', 'seeders': 1, 'downloaders': 6,
            'upload_workers': 2, 'window': 4, 'fixture_seed': 2026,
            'churn': [{'cycle': 1, 'slot': 0, 'at_s': 0, 'deadline_s': 60}]}
    plan = {'schema': 'btl-stress-pilot-v1', 'lane': 'pilot', 'source_freeze': source_freeze,
            'duration_s': 60, 'cycles': 1, 'seed': 2026, 'fixture_bytes': FIXTURE_BYTES,
            'limits': limits, 'cases': [case]}
    plan['sha256'] = _hash(plan)
    validate_pilot_plan(plan)
    return plan


def validate_pilot_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'lane', 'source_freeze', 'duration_s',
            'cycles', 'seed', 'fixture_bytes', 'limits', 'cases', 'sha256'}
            or plan['schema'] != 'btl-stress-pilot-v1' or plan['lane'] != 'pilot'
            or plan['duration_s'] != 60 or plan['cycles'] != 1 or plan['seed'] != 2026
            or plan['fixture_bytes'] != FIXTURE_BYTES
            or plan['sha256'] != _hash({k: v for k, v in plan.items() if k != 'sha256'})
            or not isinstance(plan['source_freeze'], str) or len(plan['source_freeze']) != 64
            or any(c not in '0123456789abcdef' for c in plan['source_freeze'])):
        raise ValueError('fixed preparation pilot schema/freeze/hash mismatch')
    validate_limits(plan['limits'], pilot=True)
    expected = {'case_id': 'PREPARE-PILOT-S1-L6-W2-Q4', 'seeders': 1, 'downloaders': 6,
                'upload_workers': 2, 'window': 4, 'fixture_seed': 2026,
                'churn': [{'cycle': 1, 'slot': 0, 'at_s': 0, 'deadline_s': 60}]}
    if plan['cases'] != [expected] or not (plan['limits']['settle_s'] < 20
            and plan['limits']['start_timeout_s'] <= 45 and plan['limits']['cleanup_timeout_s'] <= 15):
        raise ValueError('preparation pilot limits/configuration changed')
    return plan


def validate_workload(plan):
    return validate_pilot_plan(plan) if plan.get('schema') == 'btl-stress-pilot-v1' else validate_plan(plan)


def validate_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'lane', 'source_freeze',
            'duration_s', 'cycles', 'seed', 'fixture_bytes', 'limits', 'cases', 'sha256'}
            or plan['schema'] != 'btl-stress-plan-v1'
            or plan['lane'] not in {'diagnostic', 'acceptance'}
            or plan['sha256'] != _hash({k: v for k, v in plan.items() if k != 'sha256'})
            or not isinstance(plan['source_freeze'], str) or len(plan['source_freeze']) != 64
            or any(c not in '0123456789abcdef' for c in plan['source_freeze'])):
        raise ValueError('stress plan schema/freeze/hash mismatch')
    validate_limits(plan['limits'])
    _finite(plan['duration_s'], 'duration', 1800)
    if (type(plan['cycles']) is not int or plan['cycles'] < 100
            or type(plan['seed']) is not int or plan['seed'] < 0
            or plan['fixture_bytes'] != FIXTURE_BYTES or len(plan['cases']) != 16):
        raise ValueError('full stress duration/cycles/fixture/grid required')
    seen = []
    for index, case in enumerate(plan['cases']):
        values = tuple(case[k] for k in ('seeders', 'downloaders', 'upload_workers', 'window'))
        seen.append(values)
        if (set(case) != {'case_id', 'seeders', 'downloaders', 'upload_workers', 'window', 'fixture_seed', 'churn'}
                or any(type(value) is not int for value in values)
                or values != GRID[index]
                or case['case_id'] != f'S{values[0]}-L{values[1]}-W{values[2]}-Q{values[3]}'
                or case['fixture_seed'] != plan['seed'] + index):
            raise ValueError('stress configuration differs from full ordered cross-product')
        rng = random.Random(case['fixture_seed'])
        expected = [{'cycle': n + 1, 'slot': rng.randrange(case['downloaders']),
                     'at_s': n * plan['duration_s'] / plan['cycles'],
                     'deadline_s': (n + 1) * plan['duration_s'] / plan['cycles']}
                    for n in range(plan['cycles'])]
        if case['churn'] != expected or plan['duration_s'] / plan['cycles'] <= plan['limits']['settle_s']:
            raise ValueError('deterministic declared churn timeline differs')
    return plan


def required_disk(plan, *, case_count=16):
    # Preserve every initial/transient/replacement peer's pieces and possible
    # assembled output. This conservative bound never assumes early-stop savings.
    per_case = FIXTURE_BYTES * (1 + 2 * (10 + 2 * plan['cycles']))
    return case_count * per_case + plan['limits']['raw_log_budget_bytes'] + plan['limits']['disk_headroom_bytes']


def preflight(plan, repo, output_parent, *, case_count=16):
    validate_workload(plan)
    if plan['lane'] == 'acceptance':
        raise StressBlocked('Acceptance stress BLOCKED: no validated OS/remote source-isolation adapter or independent final stress verification is implemented. Local diagnostic workload cannot substitute.')
    if not os.environ.get('ACCEPTANCE_PROCESS_REGISTRY'):
        raise StressBlocked('stress must run inside RecordingSession with its process guardian')
    try:
        from .resources import host_inventory
        import psutil
    except ImportError as exc:
        raise StressBlocked('pinned resource/guardian dependencies are unavailable') from exc
    repo = checked_path(repo, strict=True)
    if snapshot(repo)['sha256'] != plan['source_freeze']:
        raise ValueError('stress source differs from frozen plan')
    if plan['lane'] != 'pilot':
        pilot = checked_path(repo / plan['limits']['pilot_evidence']['path'])
        if not pilot.is_file():
            raise StressBlocked('reviewed pilot evidence is unavailable')
        if not pilot.is_relative_to(repo) or digest_file(pilot) != plan['limits']['pilot_evidence']['sha256']:
            raise StressBlocked('reviewed pilot evidence is missing or differs')
    if not (repo / 'bittorrent_lite/tests/end_to_end/support.py').is_file():
        raise StressBlocked('source-checkout diagnostic Swarm support is unavailable')
    observed = host_inventory(output_parent)
    if observed['disk_free_bytes'] < required_disk(plan, case_count=case_count):
        raise StressBlocked('insufficient disk for all retained downloads/logs plus reviewed headroom')
    needed_ram = 12 * plan['limits']['peer_max']['rss_bytes'] + plan['limits']['ram_headroom_bytes']
    if observed['ram_available_bytes'] < needed_ram:
        raise StressBlocked('insufficient measured available RAM for declared process bounds/headroom')
    return observed


def gauges(metrics):
    required = {'rss_bytes', 'thread_count', 'tcp_socket_count', 'cpu_user_s', 'cpu_system_s'}
    descriptors = set(metrics) - required
    if (not required <= set(metrics) or descriptors not in ({'handle_count'}, {'file_descriptor_count'})
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in metrics.values())):
        raise ValueError('actual complete process resource sample required')
    if any(type(metrics[k]) is not int for k in set(metrics) - {'cpu_user_s', 'cpu_system_s'}):
        raise ValueError('resource counts must be actual nonnegative integers')
    return {**{k: metrics[k] for k in GAUGES[:-1]}, 'descriptor_count': metrics[next(iter(descriptors))]}


def check_gauges(actual, bounds, label):
    if (set(actual) != set(GAUGES) or set(bounds) != set(GAUGES)
            or any(type(actual[key]) is not int or actual[key] < 0 or actual[key] > bounds[key] for key in GAUGES)):
        raise ValueError(f'{label} exceeds reviewed resource limits: {actual} versus {bounds}')


def _count(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'invalid {label} count')
    return value


def wait_for_condition(predicate, poll, deadline, *, now=time.monotonic, sleep=time.sleep):
    """Enforce the deadline before/after observation, including already-true predicates."""
    while True:
        if now() >= deadline:
            raise TimeoutError('declared stress transition/settling deadline exceeded')
        poll()
        if now() >= deadline:
            raise TimeoutError('declared stress transition/settling deadline exceeded')
        ready = predicate()
        if now() >= deadline:
            raise TimeoutError('declared stress transition/settling deadline exceeded')
        if ready:
            return
        remaining = deadline - now()
        if remaining <= 0:
            raise TimeoutError('declared stress transition/settling deadline exceeded')
        sleep(min(.025, remaining))


def inspect_event(row, case, limits):
    """Pure semantic invariant check; callers must supply genuine raw events."""
    kind = row['event']
    if kind in {'resource_sample_error', 'resource_sample_unavailable'}:
        raise ValueError('resource instrumentation unavailable during stress')
    if kind == 'resource_sample':
        check_gauges(gauges(row['metrics']), limits['peer_max'], 'peer resource sample')
    if kind == 'writer_queue' and _count(row['depth'], 'writer depth') > _count(row['capacity'], 'writer capacity', 1):
        raise ValueError('writer queue capacity exceeded')
    if kind == 'scheduler_snapshot':
        if _count(row['event_queue_depth'], 'event depth') > _count(row['event_queue_capacity'], 'event capacity', 1):
            raise ValueError('event queue capacity exceeded')
        if _count(row['connected_peers'], 'connections') > 10 or len(row['neighbors']) > limits['neighbor_records']:
            raise ValueError('connection/retained neighbor bound exceeded')
        identities = [(req['connection_id'], req['request_id'], req['piece_index']) for req in row['pending']]
        if len(identities) != len(set(identities)):
            raise ValueError('duplicate pending request identity')
        for connection, request, piece in identities:
            _count(connection, 'connection', 1)
            _count(request, 'request', 1)
            _count(piece, 'piece')
        counts = Counter(req['connection_id'] for req in row['pending'])
        if any(value > case['window'] for value in counts.values()):
            raise ValueError('per-connection request window exceeded')
        if _count(row['uploads']['service']['active_jobs'], 'upload jobs') > limits['active_jobs']:
            raise ValueError('active upload job bound exceeded')
    if kind == 'status' and (row['storage_error'] or row['recovery_error'] or row['state'] == 'ERROR'):
        raise ValueError('runtime reported stress error')
    if kind == 'piece_verification' and row['outcome'] != 'stored':
        raise ValueError('unexpected verification failure during nonfault stress')


def validate_witness(proof, *, probe_name, stop_requested_mono, freshness_s):
    """Cross-check existing raw-row references; this never creates observations."""
    if set(proof) != {'send', 'receive', 'commit', 'busy_snapshot', 'upload_busy', 'writer_busy'}:
        raise ValueError('complete network and occupied-work witness required')
    send, receive, commit, busy, upload, writer = [proof[key]['row'] for key in
        ('send', 'receive', 'commit', 'busy_snapshot', 'upload_busy', 'writer_busy')]
    if (send['event'] != 'frame_sent' or receive['event'] != 'frame_received'
            or send['message_type'] != 'PIECE' or receive['message_type'] != 'PIECE'
            or send['frame_complete'] is not True or receive['frame_complete'] is not True
            or commit['event'] != 'piece_verified' or busy['event'] != 'scheduler_snapshot'
            or upload['event'] != 'scheduler_snapshot' or writer['event'] != 'writer_queue'):
        raise ValueError('wrong witness event kinds')
    if (receive['proc'] != commit['proc'] or busy['proc'] != commit['proc']
            or send['proc'] == receive['proc'] or upload['proc'] != send['proc'] or writer['proc'] != send['proc']
            or send['remote'] != probe_name or receive['remote'] != commit['remote']
            or send['local_endpoint'] != receive['remote_endpoint']
            or send['remote_endpoint'] != receive['local_endpoint']
            or any(send[k] != receive[k] for k in ('request_id', 'piece', 'payload_bytes'))
            or any(receive[k] != commit[k] for k in ('request_id', 'piece', 'connection_id', 'remote'))
            or receive['payload_bytes'] != commit['bytes'] or commit['bytes'] <= 0
            or receive['mono'] > commit['mono'] or commit['mono'] > stop_requested_mono):
        raise ValueError('wire send/receive/ownership provenance mismatch')
    if not busy['pending'] or upload['uploads']['service']['active_jobs'] <= 0 or writer['depth'] <= 0:
        raise ValueError('actual pending, upload and writer work required before churn stop')
    for row in (busy, upload, writer):
        if not 0 <= stop_requested_mono - row['mono'] <= freshness_s:
            raise ValueError('busy-work observation is stale or after stop')
    if writer['remote'] != probe_name:
        raise ValueError('occupied writer does not serve the churn peer')
    return proof


def observe_interpreter(child, launch, registry):
    """Independently bind log PID to the live owned process tree at readiness."""
    from bittorrent_lite.tests.end_to_end.support import observe_interpreter as observe_owned
    # Swarm captures at readiness; this revalidates and reuses the exact same
    # identity instead of publishing a duplicate registry record.
    return observe_owned(child, launch, registry)


class LiveAudit:
    """Bounded-memory parser; full bytes stay in each child's original raw file."""
    def __init__(self, case, limits):
        self.case, self.limits = case, limits
        self.states = {}

    def poll(self, child):
        from .measured import validate_event
        state = self.states.setdefault(child['proc_id'], {
            'offset': 0, 'line': 0, 'mono': -1, 'recent': deque(maxlen=4096),
            'resource': None, 'snapshot': None, 'complete': False, 'counts': Counter(),
            'name': child['name'], 'log_pid': None, 'maxima': {key: 0 for key in GAUGES}})
        path = child['events']
        if not path.exists():
            return state
        with path.open('rb') as handle:
            handle.seek(state['offset'])
            raw = handle.read(4 * 1024 * 1024)
        end = raw.rfind(b'\n')
        if end < 0:
            if len(raw) >= 4 * 1024 * 1024 or (raw and child['proc'].poll() is not None):
                raise ValueError('overlong or truncated gracefully stopped event record')
            return state
        for line in raw[:end].split(b'\n'):
            state['line'] += 1
            row = strict_json(line)
            if row.get('proc') != child['proc_id'] or ('peer_id' in row and row['peer_id'] != child['name']):
                raise ValueError('stress process/peer identity mismatch')
            # Swarm labels raw streams with a launch generation prefix, while
            # measured's shared schema expects the logical peer ID as proc.
            # Validate that lossless view; retain/hash the untouched raw row.
            validate_event({**row, 'proc': child['name']}, child['name'])
            if (row.get('log_schema') != 'btl-log-v1' or row.get('log_sequence') != state['line'] - 1
                    or type(row.get('log_pid')) is not int or row['log_pid'] <= 0
                    or child.get('interpreter', {}).get('pid', row['log_pid']) != row['log_pid']
                    or state['log_pid'] not in (None, row['log_pid'])):
                raise ValueError('stress strict logger sequence/interpreter identity differs')
            state['log_pid'] = row['log_pid']
            if row['mono'] < state['mono']:
                raise ValueError('stress event clock regressed')
            state['mono'] = row['mono']
            inspect_event(row, self.case, self.limits)
            state['counts'][row['event']] += 1
            entry = {'path': path.name, 'line': state['line'], 'row': row,
                     'line_sha256': hashlib.sha256(line).hexdigest()}
            state['recent'].append(entry)
            if row['event'] == 'resource_sample':
                prior = state['resource']
                if prior and row['mono'] - prior['row']['mono'] > self.limits['sample_gap_s']:
                    raise ValueError('resource observation gap exceeded reviewed maximum')
                state['resource'] = entry
                for key, value in gauges(row['metrics']).items():
                    state['maxima'][key] = max(state['maxima'][key], value)
            if row['event'] == 'scheduler_snapshot':
                state['snapshot'] = entry
            if row['event'] == 'complete':
                if row['final_hash_ok'] is not True or state['complete']:
                    raise ValueError('completion hash false or completion duplicated')
                state['complete'] = True
        state['offset'] += end + 1
        return state

    def witness(self, child, now):
        state = self.states[child['proc_id']]
        snap = state['snapshot']
        if (not state['resource'] or not snap
                or now - snap['row']['mono'] > self.limits['busy_freshness_s'] or not snap['row']['pending']):
            return None
        for commit in reversed(state['recent']):
            event = commit['row']
            if event['event'] != 'piece_verified':
                continue
            for receive in reversed(state['recent']):
                row = receive['row']
                if (row['event'] == 'frame_received' and row['message_type'] == 'PIECE'
                        and row['frame_complete'] is True and row['mono'] <= event['mono']
                        and row['payload_bytes'] == event['bytes']
                        and all(row[key] == event[key] for key in ('connection_id', 'request_id', 'piece', 'remote'))):
                    for other in self.states.values():
                        for send in reversed(other['recent']):
                            sent = send['row']
                            if (sent['event'] == 'frame_sent' and sent['message_type'] == 'PIECE'
                                    and sent['frame_complete'] is True
                                    and other['name'] == row['remote'] and sent['remote'] == child['name']
                                    and other['name'] != child['name']
                                    and sent['local_endpoint'] == row['remote_endpoint']
                                    and sent['remote_endpoint'] == row['local_endpoint']
                                    and all(sent[key] == row[key] for key in ('request_id', 'piece', 'payload_bytes'))):
                                upload_busy = next((entry for entry in reversed(other['recent'])
                                    if entry['row']['event'] == 'scheduler_snapshot'
                                    and now - entry['row']['mono'] <= self.limits['busy_freshness_s']
                                    and entry['row']['uploads']['service']['active_jobs'] > 0), None)
                                writer_busy = next((entry for entry in reversed(other['recent'])
                                    if entry['row']['event'] == 'writer_queue'
                                    and now - entry['row']['mono'] <= self.limits['busy_freshness_s']
                                    and entry['row']['remote'] == child['name']
                                    and entry['row']['depth'] > 0), None)
                                if upload_busy and writer_busy:
                                    return {'send': send, 'receive': receive, 'commit': commit,
                                            'busy_snapshot': snap, 'upload_busy': upload_busy,
                                            'writer_busy': writer_busy}
            # Only the most recent ownership commit is a current-cycle witness.
            break
        return None


def diagnostic_workload(plan, case_id, root, repo):
    """Actual long-lived workload; completion never shortens the hold interval."""
    from .resources import process_sample
    from .recording import matching_process
    from bittorrent_lite.tests.end_to_end.support import Swarm
    root, repo = checked_path(root), checked_path(repo, strict=True)
    root.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'btl-stress-case-v1', 'lane': plan['lane'], 'acceptance_eligible': False,
              'source_isolation_verified': False, 'case_id': case_id, 'plan_sha256': plan['sha256'],
              'status': 'NOT RUN', 'cycles': [], 'interpreters': [], 'limitations': [
                  'Local processes share an OS account and can read the seeder source.',
                  'Diagnostic verification is not independent final acceptance verification.',
                  'Only sampled resource maxima are claimed; between-sample peaks are not measured.']}
    swarm, cleanup_attempted = None, False
    try:
        case = next(c for c in validate_workload(plan)['cases'] if c['case_id'] == case_id)
        report['host_before'] = preflight(plan, repo, root, case_count=1)
        class InstrumentedSwarm(Swarm):
            def launch(self, name, args, **kwargs):
                if args[0] == 'bittorrent_lite':
                    args = [*args, '--resource-metrics']
                return super().launch(name, args, **kwargs)
        swarm = InstrumentedSwarm(root / 'swarm', size=FIXTURE_BYTES, fixture_seed=case['fixture_seed'])
        swarm.env['BTL_LOG_STRICT'] = '1'
        audit = LiveAudit(case, plan['limits'])
        retired = set()
        started = time.monotonic()
        hard_deadline = started + plan['limits']['start_timeout_s'] + plan['duration_s'] + plan['limits']['cleanup_timeout_s']
        def poll():
            if time.monotonic() >= hard_deadline:
                raise TimeoutError('finite stress workload deadline exceeded')
            for child in swarm.children:
                if child['proc_id'] not in retired:
                    swarm.check(child)
                state = audit.poll(child)
                if child['name'] != 'tracker' and state['resource'] and child['proc_id'] not in retired:
                    if time.monotonic() - state['resource']['row']['mono'] > plan['limits']['sample_gap_s']:
                        raise ValueError('live peer stopped producing actual resource samples')
            if shutil.disk_usage(root).free < plan['limits']['disk_headroom_bytes']:
                raise ValueError('actual free disk crossed reviewed headroom')
            if sum(path.stat().st_size for child in swarm.children
                   for path in (child['out'], child['err'], child['events']) if path.exists()) > plan['limits']['raw_log_budget_bytes'] / len(plan['cases']):
                raise ValueError('actual raw logs exceeded reserved per-configuration budget')
        def wait_until(predicate, deadline):
            wait_for_condition(predicate, poll, deadline)
        def start_peer(name, seeder=False):
            child = swarm.start_peer(name, seed=seeder, workers=case['upload_workers'], window=case['window'])
            report['interpreters'].append(observe_interpreter(child, swarm.launches[-1], os.environ['ACCEPTANCE_PROCESS_REGISTRY']))
            poll()
            return child
        def drain(child):
            while True:
                before = audit.states.get(child['proc_id'], {}).get('offset', 0)
                after = audit.poll(child)['offset']
                if after == child['events'].stat().st_size:
                    return
                if after <= before or time.monotonic() >= hard_deadline:
                    raise ValueError('incomplete final event drain or cleanup deadline exceeded')
        def stop_peer(child):
            retired.add(child['proc_id'])
            result = swarm.stop_peer(child['name'])
            drain(child)
            if (child['identity'] is None or matching_process(child['identity']) is not None
                    or matching_process(child['interpreter']) is not None):
                raise ValueError('stopped peer lacks ownership or remains alive')
            audit.states[child['proc_id']]['recent'].clear()
            return result
        swarm.start_tracker()
        report['interpreters'].append(observe_interpreter(swarm.tracker, swarm.launches[-1], os.environ['ACCEPTANCE_PROCESS_REGISTRY']))
        seeders = [start_peer(f'seed-{n}', True) for n in range(case['seeders'])]
        slots = [start_peer(f'initial-{n}') for n in range(case['downloaders'])]
        def complete_resources(children):
            poll()
            return all(audit.states[c['proc_id']]['complete'] and audit.states[c['proc_id']]['resource'] for c in children)
        wait_until(lambda: complete_resources(slots), started + plan['limits']['start_timeout_s'])
        for child in slots:
            swarm.complete(child['name'], timeout=.1)
        wait_until(lambda: all(audit.states[c['proc_id']]['resource'] for c in seeders), started + plan['limits']['start_timeout_s'])
        baseline = {child['name']: gauges(audit.states[child['proc_id']]['resource']['row']['metrics']) for child in seeders + slots}
        slot_baseline = [baseline[c['name']] for c in slots]
        owner_before = gauges(process_sample())
        origin = time.monotonic()
        report.update(started_mono=origin, baselines=baseline, supervisor_before=owner_before,
                      baseline_resources={c['proc_id']: audit.states[c['proc_id']]['resource'] for c in seeders + slots})
        for transition in case['churn']:
            deadline = origin + transition['deadline_s']
            wait_until(lambda: time.monotonic() >= origin + transition['at_s'], deadline)
            slot = transition['slot']
            old = slots[slot]
            cycle = {'cycle': transition['cycle'], 'slot': slot, 'began_mono': time.monotonic(),
                     'old': old['proc_id'], 'source_isolation_verified': False}
            stop_peer(old)
            probe = start_peer(f"cycle-{transition['cycle']:03d}-probe")
            cycle['probe'] = probe['proc_id']
            proof = None
            def occupied_with_network():
                nonlocal proof
                poll()
                proof = audit.witness(probe, time.monotonic())
                return proof is not None
            wait_until(occupied_with_network, deadline - plan['limits']['settle_s'])
            cycle['network_and_occupied_request_proof'] = proof
            cycle['stop_requested_mono'] = time.monotonic()
            validate_witness(proof, probe_name=probe['name'], stop_requested_mono=cycle['stop_requested_mono'],
                             freshness_s=plan['limits']['busy_freshness_s'])
            stop_peer(probe)
            piece = proof['commit']['row']['piece']
            piece_path = swarm.root / 'downloads' / probe['name'] / 'pieces' / f'{piece}.piece'
            actual_piece = piece_path.read_bytes()
            with swarm.source.open('rb') as source:
                source.seek(piece * 65536)
                expected_piece = source.read(65536)
            if actual_piece != expected_piece or len(actual_piece) != proof['commit']['row']['bytes']:
                raise ValueError('network witness ownership bytes differ from independent source slice')
            cycle['independent_piece'] = {'path': piece_path.relative_to(root).as_posix(),
                                          'sha256': digest_file(piece_path), 'size': len(actual_piece)}
            replacement = start_peer(f"cycle-{transition['cycle']:03d}-keeper")
            slots[slot] = replacement
            cycle['replacement'] = replacement['proc_id']
            wait_until(lambda: complete_resources([replacement]), deadline - plan['limits']['settle_s'])
            swarm.complete(replacement['name'], timeout=.1)
            settle_begin = None
            def settled():
                nonlocal settle_begin
                poll()
                for child, base in [*( (c, baseline[c['name']]) for c in seeders),
                                    *((c, slot_baseline[i]) for i, c in enumerate(slots))]:
                    state = audit.states[child['proc_id']]
                    actual = gauges(state['resource']['row']['metrics'])
                    bounds = {key: base[key] + plan['limits']['settled_growth'][key] for key in GAUGES}
                    if any(actual[key] > bounds[key] for key in GAUGES):
                        settle_begin = None
                        return False
                    if (not state['snapshot'] or state['snapshot']['row']['pending']
                            or state['snapshot']['row']['uploads']['service']['active_jobs']):
                        settle_begin = None
                        return False
                if settle_begin is None:
                    settle_begin = time.monotonic()
                return time.monotonic() - settle_begin >= plan['limits']['settle_s']
            wait_until(settled, deadline)
            cycle['settled_mono'] = time.monotonic()
            cycle['settled_since_mono'] = settle_begin
            cycle['settled_resources'] = {c['proc_id']: audit.states[c['proc_id']]['resource'] for c in seeders + slots}
            cycle['settled_snapshots'] = {c['proc_id']: audit.states[c['proc_id']]['snapshot'] for c in seeders + slots}
            report['cycles'].append(cycle)
            write_json_new(root / f"cycle-{transition['cycle']:03d}.json", cycle)
        wait_until(lambda: time.monotonic() >= origin + plan['duration_s'], hard_deadline)
        report['held_until_mono'] = time.monotonic()
        if report['held_until_mono'] - origin < plan['duration_s'] or len(report['cycles']) != plan['cycles']:
            raise ValueError('stress hold/cycle count incomplete')
        cleanup_attempted = True
        swarm.close()
        for child in swarm.children:
            retired.add(child['proc_id'])
            # Tracker termination is predeclared by Swarm; it has no peer metrics.
            if child['name'] != 'tracker':
                drain(child)
            if matching_process(child['identity']) is not None or matching_process(child['interpreter']) is not None:
                raise ValueError('owned stress process still alive after cleanup')
        owner_after = gauges(process_sample())
        check_gauges(owner_after, {key: owner_before[key] + plan['limits']['supervisor_growth'][key] for key in GAUGES}, 'post-shutdown supervisor')
        if digest_file(swarm.source) != swarm.digest:
            raise ValueError('stress source fixture changed')
        report.update(status='PASS', supervisor_after=owner_after,
                      sampled_resource_maxima={proc: state['maxima'] for proc, state in audit.states.items() if state['resource']},
                      process_results='swarm/results.json', finished_mono=time.monotonic())
        report['resource_summary'] = {
            'measurement_scope': 'this diagnostic only; sampled maxima, not instantaneous peaks or future bounds',
            'peer_sample_counts': {proc: state['counts']['resource_sample'] for proc, state in audit.states.items() if state['resource']},
            'retained_file_bytes_before_report': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
            'raw_child_log_bytes': sum(p.stat().st_size for child in swarm.children
                for p in (child['out'], child['err'], child['events']) if p.is_file()),
            'conservative_workload_bytes': required_disk(plan, case_count=len(plan['cases'])),
            'workload_case_count': len(plan['cases']),
            'conservative_formula': 'case_count * 64MiB * (1 + 2*(10 + 2*cycles)) + raw_log_budget_bytes + disk_headroom_bytes',
            'sizing_status': 'conservative mathematical upper estimate; not an experimentally established reservation'}
        swarm = None
    except StressBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        if swarm is not None and not cleanup_attempted:
            try:
                swarm.close()
            except Exception:
                report.update(status='FAIL', cleanup_exception=traceback.format_exc())
        report['files'] = [{'path': p.relative_to(root).as_posix(), 'sha256': digest_file(p), 'size': p.stat().st_size}
                           for p in sorted(root.rglob('*')) if p.is_file()]
        write_json_new(root / 'stress-result.json', report)
    return report


def verify_case(plan, case, out):
    """Re-read raw diagnostic evidence; not an independent acceptance verdict."""
    from .measured import validate_event
    validate_workload(plan)
    out = checked_path(out, strict=True)
    result_path = out / 'stress-result.json'
    value = strict_json(result_path.read_bytes())
    if (value.get('status') != 'PASS' or value.get('plan_sha256') != plan['sha256']
            or value.get('case_id') != case['case_id'] or value.get('lane') != plan['lane']
            or value.get('acceptance_eligible') is not False or value.get('source_isolation_verified') is not False):
        raise ValueError('stress worker failed, used a different plan, or claims acceptance')
    origin, until = value['started_mono'], value['held_until_mono']
    _finite(origin, 'origin'); _finite(until, 'hold end')
    if len(value['cycles']) != plan['cycles'] or until - origin < plan['duration_s']:
        raise ValueError('stress worker duration/cycle count mismatch')
    manifest = {}
    for item in value['files']:
        rel = item['path']
        if not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts or rel in manifest:
            raise ValueError('duplicate or unsafe stress artifact path')
        path = checked_path(out / rel, strict=True)
        if not path.is_relative_to(out) or path.stat().st_size != item['size'] or digest_file(path) != item['sha256']:
            raise ValueError('stress recorded artifact differs')
        manifest[rel] = item
    actual = {checked_path(p, strict=True).relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
    if actual != set(manifest) | {'stress-result.json'}:
        raise ValueError('stress artifact inventory is not exact')
    launches = strict_json((out / 'swarm/launches.json').read_bytes())
    processes = strict_json((out / 'swarm/results.json').read_bytes())
    expected_names = ['tracker'] + [f'seed-{n}' for n in range(case['seeders'])] + [f'initial-{n}' for n in range(case['downloaders'])]
    for n in range(1, plan['cycles'] + 1):
        expected_names += [f'cycle-{n:03d}-probe', f'cycle-{n:03d}-keeper']
    if ([row['name'] for row in launches] != expected_names
            or [row['name'] for row in processes['processes']] != expected_names
            or processes['cleanup_errors']):
        raise ValueError('stress process inventory/cleanup differs from deterministic lifecycle')
    observers = {row['proc_id']: row for row in value['interpreters']}
    if len(observers) != len(value['interpreters']) or set(observers) != {row['proc_id'] for row in launches}:
        raise ValueError('actual interpreter inventory is not exact')
    by_proc = {row['proc_id']: row for row in launches}
    names = {row['name']: row['proc_id'] for row in launches}
    for launch, end in zip(launches, processes['processes']):
        if (launch['identity'] != end['identity'] or launch['identity'] is None
                or launch['pid'] != end['pid'] or launch['pid'] != launch['identity']['pid']
                or type(end['exit_code']) is not int or end['exit_code'] != end['expected_exit_code']):
            raise ValueError('owned process identity/exit mismatch')
        if launch['name'] == 'tracker':
            allowed = [15] if os.name == 'nt' else [0, -15]
            if (launch['teardown'] != 'declared_tracker_platform_termination' or end['exit_code'] not in allowed
                    or end.get('termination_contract') != {'api': 'psutil.Process.terminate',
                        'platform': os.name, 'expected_exit_codes': allowed}):
                raise ValueError('tracker expected-negative teardown differs')
        elif end['exit_code'] != 0 or end['deliberate_kill'] or end['tails']:
            raise ValueError('ordinary stress peer did not stop gracefully')
        observer = observers[launch['proc_id']]
        if (observer['name'] != launch['name'] or observer['ancestry'][0] != launch['identity']
                or observer['ancestry'][-1] != observer['identity']
                or end.get('interpreter') != observer['identity']
                or end.get('interpreter_exit_code') != end['exit_code']):
            raise ValueError('interpreter observation is not bound to owned launcher')
        for key, suffix in (('stdout', '.stdout'), ('stderr', '.stderr'), ('events', '.events.jsonl')):
            if checked_path(launch[key], strict=True) != out / 'swarm' / (launch['proc_id'] + suffix):
                raise ValueError('child raw evidence path differs')
    refs = {}
    def require_ref(ref):
        if (set(ref) != {'path', 'line', 'row', 'line_sha256'} or Path(ref['path']).name != ref['path']
                or type(ref['line']) is not int or ref['line'] < 1):
            raise ValueError('invalid raw event reference')
        key = (ref['path'], ref['line'])
        if key in refs and refs[key] != ref:
            raise ValueError('conflicting event reference')
        refs[key] = ref
    for ref in value['baseline_resources'].values():
        require_ref(ref)
    seed_ids = [names[f'seed-{n}'] for n in range(case['seeders'])]
    slot_ids = [names[f'initial-{n}'] for n in range(case['downloaders'])]
    baseline_ids = seed_ids + slot_ids
    if set(value['baseline_resources']) != set(baseline_ids):
        raise ValueError('baseline resource process inventory differs')
    bases = {proc: gauges(value['baseline_resources'][proc]['row']['metrics']) for proc in baseline_ids}
    intervals = {proc: [] for proc in by_proc}
    source = checked_path(out / 'swarm/original bytes.bin', strict=True)
    if source.stat().st_size != FIXTURE_BYTES or digest_file(source) != processes['sha256']:
        raise ValueError('independent stress source size/hash differs')
    for transition, cycle in zip(case['churn'], value['cycles']):
        n, slot = transition['cycle'], transition['slot']
        probe, keeper = names[f'cycle-{n:03d}-probe'], names[f'cycle-{n:03d}-keeper']
        if (cycle['cycle'] != n or cycle['slot'] != slot or cycle['old'] != slot_ids[slot]
                or cycle['probe'] != probe or cycle['replacement'] != keeper
                or cycle['source_isolation_verified'] is not False
                or cycle != strict_json((out / f'cycle-{n:03d}.json').read_bytes())
                or not origin + transition['at_s'] <= cycle['began_mono'] <= cycle['stop_requested_mono']
                    <= cycle['settled_since_mono'] <= cycle['settled_mono'] <= origin + transition['deadline_s']
                or cycle['settled_mono'] - cycle['settled_since_mono'] < plan['limits']['settle_s']):
            raise ValueError('actual churn lifecycle/timing differs from declared schedule')
        proof = validate_witness(cycle['network_and_occupied_request_proof'], probe_name=by_proc[probe]['name'],
            stop_requested_mono=cycle['stop_requested_mono'], freshness_s=plan['limits']['busy_freshness_s'])
        if (proof['receive']['row']['proc'] != probe or proof['send']['row']['proc'] not in seed_ids + slot_ids
                or by_proc[proof['send']['row']['proc']]['name'] != proof['receive']['row']['remote']
                or any(not cycle['began_mono'] <= ref['row']['mono'] <= cycle['stop_requested_mono'] for ref in proof.values())):
            raise ValueError('churn evidence does not identify current live peers')
        for ref in proof.values():
            require_ref(ref)
        piece = proof['commit']['row']['piece']
        piece_ref = cycle['independent_piece']
        expected_piece_path = f"swarm/downloads/{by_proc[probe]['name']}/pieces/{piece}.piece"
        if piece_ref['path'] != expected_piece_path or manifest[expected_piece_path] != piece_ref:
            raise ValueError('committed piece artifact differs')
        with source.open('rb') as handle:
            handle.seek(piece * 65536)
            expected_piece = handle.read(65536)
        if (checked_path(out / piece_ref['path'], strict=True).read_bytes() != expected_piece
                or len(expected_piece) != proof['commit']['row']['bytes']):
            raise ValueError('network ownership bytes differ from independent source slice')
        bases[keeper] = bases[slot_ids[slot]]
        slot_ids[slot] = keeper
        active = seed_ids + slot_ids
        if set(cycle['settled_resources']) != set(active) or set(cycle['settled_snapshots']) != set(active):
            raise ValueError('settled active process inventory differs')
        for proc in active:
            ref, snap = cycle['settled_resources'][proc], cycle['settled_snapshots'][proc]
            require_ref(ref); require_ref(snap)
            bound = {key: bases[proc][key] + plan['limits']['settled_growth'][key] for key in GAUGES}
            check_gauges(gauges(ref['row']['metrics']), bound, 'settled peer')
            if (ref['row']['event'] != 'resource_sample' or ref['row']['proc'] != proc
                    or snap['row']['event'] != 'scheduler_snapshot' or snap['row']['proc'] != proc
                    or snap['row']['pending'] or snap['row']['uploads']['service']['active_jobs']
                    or not 0 <= cycle['settled_mono'] - ref['row']['mono'] <= plan['limits']['sample_gap_s']):
                raise ValueError('settled resource/idle observation differs or is stale')
            intervals[proc].append({'begin': cycle['settled_since_mono'], 'end': cycle['settled_mono'], 'bounds': bound, 'samples': 0})
    found = set()
    for launch in launches:
        proc = launch['proc_id']
        previous, last_resource, resource_count, exit_count, complete_count = -1, None, 0, 0, 0
        maximum = {key: 0 for key in GAUGES}
        with Path(launch['events']).open('rb') as stream:
            for number, raw in enumerate(stream, 1):
                if not raw.endswith(b'\n'):
                    if launch['name'] == 'tracker' and processes['processes'][0]['deliberate_kill']:
                        continue
                    raise ValueError('truncated ordinary peer event line')
                row = strict_json(raw[:-1])
                if (row['proc'] != proc or row.get('log_sequence') != number - 1
                        or row.get('log_pid') != observers[proc]['identity']['pid'] or row['mono'] < previous):
                    raise ValueError('raw event sequence/identity/time differs')
                validate_event({**row, 'proc': launch['name']}, launch['name'])
                inspect_event(row, case, plan['limits'])
                previous = row['mono']
                key = (Path(launch['events']).name, number)
                if key in refs:
                    if refs[key]['row'] != row or refs[key]['line_sha256'] != hashlib.sha256(raw[:-1]).hexdigest():
                        raise ValueError('witness differs from genuine raw event line')
                    found.add(key)
                if row['event'] == 'resource_sample':
                    if last_resource is not None and row['mono'] - last_resource > plan['limits']['sample_gap_s']:
                        raise ValueError('raw resource sample gap exceeds limit')
                    last_resource, resource_count = row['mono'], resource_count + 1
                    for gauge, metric in gauges(row['metrics']).items():
                        maximum[gauge] = max(maximum[gauge], metric)
                if row['event'] == 'complete':
                    if row['final_hash_ok'] is not True:
                        raise ValueError('raw completion hash failed')
                    complete_count += 1
                if row['event'] == 'exit':
                    if row['reason'] != 'stopped':
                        raise ValueError('unexpected runtime exit reason')
                    exit_count += 1
                for interval in intervals[proc]:
                    if interval['begin'] <= row['mono'] <= interval['end']:
                        if row['event'] == 'resource_sample':
                            check_gauges(gauges(row['metrics']), interval['bounds'], 'settling interval')
                            interval['samples'] += 1
                        if row['event'] == 'scheduler_snapshot' and (row['pending'] or row['uploads']['service']['active_jobs']):
                            raise ValueError('work remained occupied during declared settled interval')
        if launch['name'] != 'tracker':
            if (resource_count < 1 or exit_count != 1
                    or maximum != value['sampled_resource_maxima'][proc]
                    or any(interval['samples'] < 2 for interval in intervals[proc])):
                raise ValueError('resource maxima/settling coverage/normal exit evidence incomplete')
            if launch['name'].startswith(('initial-', 'cycle-')) and not launch['name'].endswith('-probe'):
                output = out / 'swarm/downloads' / launch['name'] / source.name
                if complete_count != 1 or output.stat().st_size != FIXTURE_BYTES or digest_file(output) != processes['sha256']:
                    raise ValueError('completed downloader final bytes/hash mismatch')
    if found != set(refs):
        raise ValueError('one or more witness references were not present in raw event files')
    check_gauges(value['supervisor_after'], {key: value['supervisor_before'][key] + plan['limits']['supervisor_growth'][key]
                 for key in GAUGES}, 'post-shutdown supervisor')
    return {'case_id': case['case_id'], 'status': 'PASS', 'lane': plan['lane'],
            'acceptance_eligible': False, 'result': str(result_path), 'result_sha256': digest_file(result_path)}


def run_cases(plan, execute_one, verify_one):
    """Exact one-at-a-time schedule; dependency-injected unit tests are helper-only."""
    validate_workload(plan)
    results = []
    for case in plan['cases']:
        evidence = execute_one(case)
        verified = verify_one(case, evidence)
        if verified.get('status') != 'PASS' or verified.get('case_id') != case['case_id']:
            raise ValueError('stress case failed semantic verification; full restart required')
        results.append(verified)
    return results


def supervise(plan_path, root, repo):
    from .recording import RecordingSession
    plan_path, repo, root = checked_path(plan_path, strict=True), checked_path(repo, strict=True), checked_path(root)
    plan = strict_json(plan_path.read_bytes())
    root.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'btl-stress-supervision-v1', 'status': 'NOT RUN', 'acceptance_eligible': False,
              'results': [], 'plan_sha256': plan.get('sha256')}
    frozen = snapshot(repo)
    write_json_new(root / 'source-before.json', frozen)
    try:
        report['host'] = preflight(plan, repo, root, case_count=len(plan['cases']))
        recorder = RecordingSession(root / 'commands', 'stress-preparation', 'diagnostic', {'source': frozen['sha256']})
        def execute(case):
            out = root / case['case_id']
            recorder.run(case['case_id'], [sys.executable, '-m', 'bittorrent_lite.acceptance_tools.stress',
                'worker', '--plan', str(plan_path), '--case-id', case['case_id'], '--out', str(out), '--repo', str(repo)],
                cwd=repo, timeout_s=plan['duration_s'] + plan['limits']['start_timeout_s'] + plan['limits']['cleanup_timeout_s'] + 30,
                oracle='Exact full-duration real stress case, 100+ declared busy churn cycles, network evidence, resources and owned cleanup.')
            return out
        def verify(case, out):
            return verify_case(plan, case, out)
        def retain(case, out):
            value = verify(case, out)
            report['results'].append(value)
            return value
        run_cases(plan, execute, retain)
        report['status'] = 'PASS'
    except StressBlocked as exc:
        report.update(status='BLOCKED', reason=str(exc))
    except Exception:
        report.update(status='FAIL', exception=traceback.format_exc())
    finally:
        try:
            after = snapshot(repo)
            write_json_new(root / 'source-after.json', after)
            compare_snapshots(frozen, after)
        except Exception:
            report.update(status='FAIL', source_exception=traceback.format_exc())
        write_json_new(root / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('plan')
    build.add_argument('--limits', type=Path, required=True)
    build.add_argument('--source-freeze', required=True)
    build.add_argument('--duration-s', type=float, default=1800)
    build.add_argument('--cycles', type=int, default=100)
    build.add_argument('--seed', type=int, default=2026)
    build.add_argument('--lane', choices=('diagnostic', 'acceptance'), default='diagnostic')
    build.add_argument('--out', type=Path, required=True)
    pilot = commands.add_parser('pilot', help='Fixed 60s/one-cycle PREPARE diagnostic; never acceptance credit')
    pilot.add_argument('--limits', type=Path, required=True)
    pilot.add_argument('--source-freeze', required=True)
    pilot.add_argument('--out', type=Path, required=True)
    pilot.add_argument('--repo', type=Path, required=True)
    for name in ('run', 'worker'):
        command = commands.add_parser(name)
        for field in ('plan', 'out', 'repo'):
            command.add_argument('--' + field, type=Path, required=True)
        if name == 'worker':
            command.add_argument('--case-id', required=True)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        plan = make_plan(source_freeze=args.source_freeze, limits=strict_json(args.limits.read_bytes()),
                         duration_s=args.duration_s, cycles=args.cycles, seed=args.seed, lane=args.lane)
        write_json_new(checked_path(args.out), plan)
        print(json.dumps({'status': 'PLANNED_NOT_RUN', 'plan_sha256': plan['sha256']}))
        return 0
    if args.command == 'pilot':
        root = checked_path(args.out)
        root.mkdir(parents=True, exist_ok=False)
        plan = make_pilot_plan(source_freeze=args.source_freeze, limits=strict_json(args.limits.read_bytes()))
        plan_path = root / 'pilot-plan.json'
        write_json_new(plan_path, plan)
        report = supervise(plan_path, root / 'run', args.repo)
        print(json.dumps({'status': report['status'], 'acceptance_eligible': False, 'lane': 'pilot'}))
        return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2, 'NOT RUN': 2}[report['status']]
    report = (supervise(args.plan, args.out, args.repo) if args.command == 'run'
              else diagnostic_workload(strict_json(args.plan.read_bytes()), args.case_id, args.out, args.repo))
    print(json.dumps({'status': report['status'], 'acceptance_eligible': False}))
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2, 'NOT RUN': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())

"""PREPARE helper unit tests only; synthetic rows never supply network credit.

These tests do not run the stress workload, start processes, or open sockets.
Real pilot/grid evidence must come from separately recorded commands.
"""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from bittorrent_lite.acceptance_tools import stress


def limits(*, pilot=False):
    return {'peer_max': dict(rss_bytes=512 * 1024 ** 2, thread_count=128,
                            tcp_socket_count=64, descriptor_count=1024),
            'settled_growth': dict(rss_bytes=128 * 1024 ** 2, thread_count=8,
                                   tcp_socket_count=8, descriptor_count=64),
            'supervisor_growth': dict(rss_bytes=256 * 1024 ** 2, thread_count=4,
                                      tcp_socket_count=4, descriptor_count=64),
            'active_jobs': 40, 'neighbor_records': 1024, 'sample_gap_s': 3,
            'busy_freshness_s': 1, 'settle_s': 3, 'start_timeout_s': 45,
            'cleanup_timeout_s': 15, 'disk_headroom_bytes': 1024 ** 3,
            'raw_log_budget_bytes': 1024 ** 3, 'ram_headroom_bytes': 1024 ** 3,
            'pilot_evidence': None if pilot else {'path': '.validation/unit-only-pilot.json', 'sha256': 'a' * 64}}


def plan():
    return stress.make_plan(source_freeze='f' * 64, limits=limits())


def reseal(value):
    value['sha256'] = stress._hash({k: v for k, v in value.items() if k != 'sha256'})


def metrics():
    return dict(rss_bytes=1000, thread_count=2, tcp_socket_count=1,
                cpu_user_s=.1, cpu_system_s=.2, handle_count=10)


def snapshot_row():
    return {'event': 'scheduler_snapshot', 'event_queue_depth': 1, 'event_queue_capacity': 64,
            'connected_peers': 2, 'neighbors': {}, 'pending': [{'connection_id': 2, 'request_id': 3, 'piece_index': 0}],
            'uploads': {'service': {'active_jobs': 1}}}


def test_full_stress_plan_is_exact_cross_product_and_never_shortened():
    value = plan()
    assert len(value['cases']) == 16
    assert sum(value['duration_s'] for _ in value['cases']) == 8 * 3600
    assert [(c['seeders'], c['downloaders'], c['upload_workers'], c['window']) for c in value['cases']] == list(stress.GRID)
    assert all(len(c['churn']) == 100 and c['churn'][0]['at_s'] == 0
               and c['churn'][-1]['deadline_s'] == 1800 for c in value['cases'])
    assert value == plan()
    assert len({tuple(c['slot'] for c in case['churn']) for case in value['cases']}) == 16


@pytest.mark.parametrize('change', ['duration', 'cycles', 'missing', 'duplicate', 'window', 'timeline', 'seed', 'hash'])
def test_changed_stress_contract_rejected_even_if_rehashed(change):
    value = plan()
    if change == 'duration': value['duration_s'] = 1799
    elif change == 'cycles': value['cycles'] = 99
    elif change == 'missing': value['cases'].pop()
    elif change == 'duplicate': value['cases'][1] = copy.deepcopy(value['cases'][0])
    elif change == 'window': value['cases'][0]['window'] = 2
    elif change == 'timeline': value['cases'][0]['churn'][0]['slot'] = 999
    elif change == 'seed': value['cases'][0]['fixture_seed'] += 1
    elif change == 'hash': value['sha256'] = '0' * 64
    if change != 'hash': reseal(value)
    with pytest.raises(ValueError):
        stress.validate_plan(value)


def test_pilot_has_distinct_fixed_contract_not_accepted_as_grid():
    value = stress.make_pilot_plan(source_freeze='f' * 64, limits=limits(pilot=True))
    assert value['lane'] == 'pilot' and value['duration_s'] == 60 and value['cycles'] == 1
    assert len(value['cases']) == 1 and value['cases'][0]['case_id'].startswith('PREPARE-PILOT-')
    assert stress.validate_pilot_plan(value) is value
    with pytest.raises(ValueError):
        stress.validate_plan(value)
    value['duration_s'] = 10
    reseal(value)
    with pytest.raises(ValueError):
        stress.validate_pilot_plan(value)


@pytest.mark.parametrize('key,value', [('sample_gap_s', 4), ('busy_freshness_s', 2),
                                      ('settle_s', 1), ('raw_log_budget_bytes', 0), ('start_timeout_s', float('inf'))])
def test_missing_or_weakened_resource_observation_limits_rejected(key, value):
    reviewed = limits()
    reviewed[key] = value
    with pytest.raises(ValueError):
        stress.validate_limits(reviewed)


def test_no_pilot_evidence_cannot_authorize_full_grid():
    with pytest.raises(stress.StressBlocked):
        stress.make_plan(source_freeze='f' * 64, limits=limits(pilot=True))


def test_acceptance_and_unrecorded_work_block_before_resources_or_launch(monkeypatch, tmp_path):
    value = stress.make_plan(source_freeze='f' * 64, limits=limits(), lane='acceptance')
    monkeypatch.setattr(stress, 'snapshot', lambda *_: pytest.fail('must block before source/resource work'))
    with pytest.raises(stress.StressBlocked, match='source-isolation'):
        stress.preflight(value, tmp_path, tmp_path)
    monkeypatch.delenv('ACCEPTANCE_PROCESS_REGISTRY', raising=False)
    with pytest.raises(stress.StressBlocked, match='RecordingSession'):
        stress.preflight(plan(), tmp_path, tmp_path)


def test_disk_budget_retains_every_generation_and_does_not_claim_measured_reservation():
    value = plan()
    expected = 16 * stress.FIXTURE_BYTES * (1 + 2 * (10 + 200)) + 2 * 1024 ** 3
    assert stress.required_disk(value) == expected
    assert stress.required_disk(value, case_count=1) < expected


def test_scheduler_stops_after_first_failed_semantic_result():
    visited = []
    def execute(case):
        visited.append(case['case_id'])
        return {'unit_fixture': True}
    def verify(case, fixture):
        assert fixture['unit_fixture']
        return {'case_id': case['case_id'], 'status': 'FAIL' if len(visited) == 3 else 'PASS'}
    with pytest.raises(ValueError, match='full restart'):
        stress.run_cases(plan(), execute, verify)
    assert len(visited) == 3


def test_scheduler_never_continues_after_command_exception():
    visited = []
    def fail(case):
        visited.append(case['case_id'])
        raise RuntimeError('unit fixture failed command')
    with pytest.raises(RuntimeError):
        stress.run_cases(plan(), fail, lambda *_: pytest.fail('no oracle after command exception'))
    assert len(visited) == 1


def test_expired_deadline_rejects_even_an_already_true_predicate_without_polling():
    with pytest.raises(TimeoutError, match='deadline exceeded'):
        stress.wait_for_condition(lambda: pytest.fail('expired predicate must not run'),
            lambda: pytest.fail('expired poll must not run'), 10, now=lambda: 10,
            sleep=lambda _: pytest.fail('must not sleep'))


@pytest.mark.parametrize('slow_part', ['poll', 'predicate'])
def test_deadline_crossed_during_observation_cannot_return_pass(slow_part):
    clock = [9.9]
    def poll():
        if slow_part == 'poll':
            clock[0] = 10
    def predicate():
        if slow_part == 'poll':
            pytest.fail('predicate must not follow an over-deadline poll')
        clock[0] = 10
        return True
    with pytest.raises(TimeoutError, match='deadline exceeded'):
        stress.wait_for_condition(predicate, poll, 10, now=lambda: clock[0],
                                 sleep=lambda _: pytest.fail('must not sleep'))


def test_waiting_condition_polls_until_true_inside_deadline_without_real_sleep():
    clock, polls, sleeps = [0.0], [], []
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    stress.wait_for_condition(lambda: clock[0] >= .05, lambda: polls.append(clock[0]),
                              1, now=lambda: clock[0], sleep=sleep)
    assert len(polls) == 3 and sleeps == [.025, .025] and clock[0] == .05


@pytest.mark.parametrize('mutation', ['missing-cpu', 'negative', 'boolean', 'fractional-count', 'both-descriptors'])
def test_resource_gauges_require_complete_actual_numeric_shape(mutation):
    value = metrics()
    if mutation == 'missing-cpu': del value['cpu_user_s']
    elif mutation == 'negative': value['rss_bytes'] = -1
    elif mutation == 'boolean': value['thread_count'] = True
    elif mutation == 'fractional-count': value['thread_count'] = 1.5
    elif mutation == 'both-descriptors': value['file_descriptor_count'] = 4
    with pytest.raises(ValueError):
        stress.gauges(value)


@pytest.mark.parametrize('change', ['event-queue', 'window', 'duplicate', 'jobs', 'negative-jobs', 'connections'])
def test_snapshot_resource_bounds_detect_real_invariant_violations(change):
    row = snapshot_row()
    if change == 'event-queue': row['event_queue_depth'] = 65
    elif change == 'window': row['pending'].append({'connection_id': 2, 'request_id': 4, 'piece_index': 1})
    elif change == 'duplicate': row['pending'].append(dict(row['pending'][0]))
    elif change == 'jobs': row['uploads']['service']['active_jobs'] = 41
    elif change == 'negative-jobs': row['uploads']['service']['active_jobs'] = -1
    elif change == 'connections': row['connected_peers'] = 11
    with pytest.raises(ValueError):
        stress.inspect_event(row, plan()['cases'][0], limits())


def witness():
    # Explicit synthetic helper fixture; this is not retained as run evidence.
    send = dict(event='frame_sent', proc='01-seed-0', mono=9.1, message_type='PIECE', frame_complete=True,
                local_endpoint=['127.0.0.1', 4000], remote_endpoint=['127.0.0.1', 5000],
                request_id=3, piece=1, payload_bytes=65536, remote='probe')
    receive = dict(send, event='frame_received', proc='02-probe', mono=9.2, remote='seed-0',
                   local_endpoint=list(send['remote_endpoint']), remote_endpoint=list(send['local_endpoint']), connection_id=2)
    commit = dict(event='piece_verified', proc='02-probe', mono=9.3, connection_id=2,
                  remote='seed-0', request_id=3, piece=1, bytes=65536)
    busy = dict(snapshot_row(), proc='02-probe', mono=9.4)
    upload = dict(snapshot_row(), proc='01-seed-0', mono=9.4)
    writer = dict(event='writer_queue', proc='01-seed-0', mono=9.5, remote='probe', depth=1)
    return {name: {'row': row} for name, row in zip(
        ('send', 'receive', 'commit', 'busy_snapshot', 'upload_busy', 'writer_busy'),
        (send, receive, commit, busy, upload, writer))}


def test_network_witness_reconciles_send_receive_commit_and_occupied_work():
    proof = witness()
    assert stress.validate_witness(proof, probe_name='probe', stop_requested_mono=10, freshness_s=1) is proof


@pytest.mark.parametrize('change', ['missing-send', 'endpoint', 'request', 'bytes', 'empty-pending',
                                   'empty-upload', 'empty-writer', 'stale', 'future', 'wrong-writer'])
def test_network_witness_rejects_missing_mismatched_or_stale_evidence(change):
    proof = witness()
    if change == 'missing-send': del proof['send']
    elif change == 'endpoint': proof['send']['row']['local_endpoint'][1] += 1
    elif change == 'request': proof['commit']['row']['request_id'] += 1
    elif change == 'bytes': proof['commit']['row']['bytes'] -= 1
    elif change == 'empty-pending': proof['busy_snapshot']['row']['pending'] = []
    elif change == 'empty-upload': proof['upload_busy']['row']['uploads']['service']['active_jobs'] = 0
    elif change == 'empty-writer': proof['writer_busy']['row']['depth'] = 0
    elif change == 'stale': proof['busy_snapshot']['row']['mono'] = 8
    elif change == 'future': proof['writer_busy']['row']['mono'] = 11
    elif change == 'wrong-writer': proof['writer_busy']['row']['remote'] = 'other'
    with pytest.raises(ValueError):
        stress.validate_witness(proof, probe_name='probe', stop_requested_mono=10, freshness_s=1)


def test_live_parser_keeps_partial_lines_then_checks_sequence_and_observed_pid(tmp_path):
    path = tmp_path / '02-probe.events.jsonl'
    child = {'proc_id': '02-probe', 'name': 'probe', 'events': path,
             'proc': SimpleNamespace(poll=lambda: None), 'interpreter': {'pid': 123}}
    audit = stress.LiveAudit(plan()['cases'][0], limits())
    row = dict(event='resource_sample', proc=child['proc_id'], mono=1, peer_id='probe', at=1,
               metrics=metrics(), log_schema='btl-log-v1', log_sequence=0, log_pid=123)
    raw = json.dumps(row).encode()
    path.write_bytes(raw)
    assert audit.poll(child)['line'] == 0
    path.write_bytes(raw + b'\n')
    state = audit.poll(child)
    assert state['line'] == 1 and state['resource']['line_sha256'] == hashlib.sha256(raw).hexdigest()
    row.update(log_sequence=1, mono=2, at=2, log_pid=999)
    with path.open('ab') as handle:
        handle.write(json.dumps(row).encode() + b'\n')
    with pytest.raises(ValueError, match='interpreter identity'):
        audit.poll(child)


def test_dead_peer_partial_record_is_not_silently_discarded(tmp_path):
    path = tmp_path / 'partial.events.jsonl'
    path.write_bytes(b'{"event":')
    child = {'proc_id': '02-probe', 'name': 'probe', 'events': path, 'proc': SimpleNamespace(poll=lambda: 0)}
    with pytest.raises(ValueError, match='truncated'):
        stress.LiveAudit(plan()['cases'][0], limits()).poll(child)


def test_offline_verifier_rejects_fabricated_case_pass_without_complete_evidence(tmp_path):
    value = plan()
    (tmp_path / 'stress-result.json').write_text(json.dumps({'status': 'PASS', 'plan_sha256': value['sha256'],
        'case_id': value['cases'][0]['case_id'], 'lane': 'diagnostic', 'acceptance_eligible': True}), encoding='utf-8')
    with pytest.raises(ValueError, match='claims acceptance'):
        stress.verify_case(value, value['cases'][0], tmp_path)

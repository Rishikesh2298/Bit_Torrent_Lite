# Part 3 recovery-policy integration

The original-plan project defaults now disable endgame duplication. The optional
endgame behavior below is retained only for explicit extension configurations.
Timer ticks now refill eligible work. See [original-plan alignment](../integration/original-plan-alignment.md).

The supplied `recovery_policy_part3.zip` is imported unchanged at the Python
source level as `bittorrent_lite.scheduling.recovery`. Its README is placed inside that directory
to preserve the project's main README. The original ZIP is unchanged.
The library remains independently usable through Python or JSON lines:

```sh
python -m bittorrent_lite.scheduling.recovery
```

## Scheduler behavior

The coordinator now combines three responsibilities without duplicating them:

- PiecePicker counts neighborhood availability, including choking neighbors.
- RecoveryPolicy filters eligible candidates and maintains provider/piece penalties.
- PipelineManager owns live requests, slots, identity, verification and ownership.

The default strategy remains rarest-first, with randomized ties. Sequential
and random strategies can be selected through `RecoveryConfig`. The caller's
existing `rng` argument, when supplied, provides the recovery RNG seed;
otherwise `SchedulerConfig.recovery_seed` defaults to zero.
The coordinator selects globally among eligible pieces before choosing a source,
so an earlier source cannot force a common piece ahead of a requestable rare one.

Only successful removal of a matching live request records failure. Replayed
rejections, duplicate responses and late send failures cannot penalize a
replacement. Provider identity, rather than connection ID, keys the penalties,
so reconnecting does not reset them. Provider IDs must be nonempty strings
of at most 128 characters before registration can succeed.

| Event | Recovery effect |
|---|---|
| Response timeout or REJECT | 2, 4, then 10-second backoff for that provider/piece |
| Enqueue failure, send failure, unconfirmed send | One-second cooldown, no retry-streak increment |
| Invalid bytes | Exclude that provider for the piece until verified success |
| Choke or disconnect | Count each removed live request; retain existing penalties |
| Local storage error | Pause scheduling; no provider-corruption penalty |
| Verified success | Mark owned and remove all providers' penalties for the piece |

Different providers may supply a penalized piece immediately. A successful
piece is synchronized between policy, pipeline and the coordinator's local
bitfield. Initially verified local pieces are also initialized as policy-owned.
Recovery success counters include those initially owned pieces.

`tick()` expires requests and records penalties but does not refill slots.
The owner loop must continue calling both methods periodically, even when no
messages arrive, so cooldown expiry and endgame age can trigger new work:

```python
bridge.drain(scheduler)
scheduler.tick()
scheduler.schedule()
```

## Endgame and cancellation

With at most four pieces still missing, when no eligible source offers an
unreserved candidate, a sent request at least five seconds old may get one
additional copy from a different provider. The candidate must pass its own
cooldown, exclusion, connection permission, availability and window checks.
Unsent or verifying requests never trigger duplicates. The pipeline caps
copies at two and permits only one verification per piece.

The first verified winner removes other reservations and dispatches a
`Cancel(request_id, piece_index)` via SchedulerBridge. Timeout and permission
cleanup also attempt cancellation. A failed CANCEL enqueue is reported in
scheduler problems without undoing ownership or resurrecting reservations.
Late responses are harmless because full request identity is checked.
Legacy transports without `send_cancel` retain ordinary downloads but do not
issue endgame duplicates. The real networking branch and peer loop are not
merged here: sending a CANCEL message through the bridge is verified; actual
socket-side removal of queued work remains a networking integration concern.

## Configuration and capacity

```python
from bittorrent_lite.scheduling import SchedulerConfig
from bittorrent_lite.scheduling.recovery import RecoveryConfig

config = SchedulerConfig(
    request_window=4,
    recovery_seed=7,
    recovery=RecoveryConfig(
        strategy="rarest-first",
        retry_delays=(2.0, 4.0, 10.0),
        endgame_enabled=True,
        endgame_min_age=5.0,
        max_copies=2,
    ),
)
```

Policy defaults bound the ledger to 256 providers and 4,096 provider/piece
records; recent events are bounded to 256. Expired records retain streaks.
No record is silently evicted. If recording a required penalty exceeds capacity,
request accounting is cleaned and new reservations pause with `recovery_error`.
Already outstanding work can still finish. The pause is intentionally latched;
`resume_after_storage_error()` cannot clear it. A new session with appropriate
capacity and revalidated local ownership is needed to restart after this error.

`snapshot()['recovery']` exposes owned pieces, counters, penalties, cooldowns
and bounded history. `paused` covers both storage and recovery errors.
The pre-existing bridge event queue and scheduler diagnostic lists remain
unbounded; the policy's bounds do not imply a bounded whole application.

## Verification

Verified on 17 October 2026: **307 passed, 56 skipped**, including 55 new
recovery cases. The skips are existing legacy placeholders. The scheduler demo
and `git diff --check` also pass. This device used the bundled Python runtime,
existing pytest dependencies in `env/test-deps`, and a local temporary directory.

Run from the repository root with Python and pytest:

```sh
python -m pytest -q --basetemp=env/part3-tests
```

New tests cover deterministic ranking, retry boundaries and streaks, exclusions,
capacity atomicity and cleanup, immutable snapshots, malformed inputs and RNG
state, bounded event history, CLI errors, reconnect persistence, stale events,
local-send failures, both endgame winners, corrupt competing responses, CANCEL
failure, disk errors, seeded selection, initial ownership and real-file
reconstruction through the protocol bridge. Earlier tests were updated where
Part 3 deliberately replaces immediate retry with cooldown or provider exclusion.

These are local policy/accounting and bridge/storage tests, not proof of a
working TCP swarm. No commit, push, merge or pull request is part of this work.

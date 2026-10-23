# Project documentation

All project folders live inside `BitTorrent/bittorrent_lite/`. Paths in commands
are relative to the `BitTorrent/` repository root unless stated otherwise.

- [Architecture and portable setup](architecture.md)
- [Member ownership](ownership.md)
- [Original project guide](plans/original/BitTorrent-Lite-Revised-Project-Guide.md)
- [Rishikesh: storage](rishikesh/README.md)
- [Debargha: tracker](debargha/tracker.md), [experiments](debargha/experiment-method.md), [log events](debargha/log-events.md), [browser GUI](debargha/gui.md)
- [Anik: protocol](anik/protocol_spec.md)
- [Prabhat: scheduler](prabhat/scheduler.md), [requests](prabhat/request-pipeline.md), [recovery](prabhat/recovery-policy.md), [uploads](prabhat/upload-and-choking.md)
- [Integration handoff](integration/peer-runtime-handoff.md)
- [Real backend and portable CLI guide](integration/real-network-backend.md)
- [Fresh installation and teammate-device runbook](integration/TEAM-RUNBOOK.md)
- [Current JSON wire protocol](integration/CURRENT-WIRE-PROTOCOL.md)
- [Final acceptance controlling plan](integration/FINAL-ACCEPTANCE-TEST-PLAN.md)
- [Post-merge acceptance plan](integration/post-merge-testing.md)
- [Layout migration and validation status](integration/layout-migration.md)
- [Unit-stage report — 537 passed](integration/unit-validation-2026-10-22.md)
- [Integration/system report — all 200 passed, plus 537 unit regressions](integration/integration-validation-2026-10-22.md)
- [Real end-to-end report — complete suite 784 passed](integration/end-to-end-validation-2026-10-22.md)
- [Complete old-to-new file map](integration/path-migration.json)

Original plans are preserved verbatim as planning references, not current path
instructions or evidence of completed work. Follow-up plans are under
`plans/follow-up/`. Historical test results in existing documents describe their
original revisions. The real backend is now connected and all 784 collected
tests passed, including 33 real end-to-end cases on Windows localhost. The older
unit/integration reports retain their original stage-specific results and limits.
The final acceptance preparation changes require new validation. Those historical
counts do not establish a pass for the current source or external-device cases.

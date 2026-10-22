"""
Experiment harness (Debargha).

    make_fixture.py   deterministic test file + metadata
    launcher.py       run one swarm from a JSON config, write manifest
    matrix.py         the 9-configuration matrix with repeats
    collect.py        run folders -> runs.csv / peers.csv / availability.csv
    plot.py           CSVs -> figures + summary.csv
    stand_in_peer.py  synthetic peer for testing the harness only

See bittorrent_lite/docs/debargha/experiment-method.md.
"""

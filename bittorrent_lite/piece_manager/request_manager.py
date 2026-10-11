"""Public request manager, implemented by the integrated Part 1 scheduler.

The old piece-only stub API is replaced by explicit connection/request/piece
identity. Construct with a Clock and SchedulerConfig; see docs/scheduler.md.
All mutations belong to the coordinator owner thread.
"""
from bittorrent_lite.scheduler.request_manager import RequestManager

__all__ = ["RequestManager"]

"""Choking module — legacy shim.

The old rate-only ChokingManager scaffold had no implementation or callers.
Use ProjectUploadPolicy directly (from bittorrent_lite.scheduler.upload_policy),
or SchedulerBridge.create_coordinator(store).
"""

from bittorrent_lite.scheduler.upload_policy import ProjectUploadPolicy  # noqa: F401

__all__ = ["ProjectUploadPolicy"]

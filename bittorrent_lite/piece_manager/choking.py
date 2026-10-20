"""Compatibility import for the implemented, acknowledged project policy.

The old rate-only ChokingManager scaffold had no implementation or callers.
It could not represent interest, send acknowledgements or bounded slot changes.
Use ProjectUploadPolicy directly, or SchedulerBridge.create_coordinator(store).
"""
from bittorrent_lite.scheduler.upload_policy import ProjectUploadPolicy

__all__ = ["ProjectUploadPolicy"]

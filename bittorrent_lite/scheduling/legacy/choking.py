"""Choking module — legacy shim.

Retain the network contribution's ChokingManager and the coordinator's
ProjectUploadPolicy as distinct public interfaces. The merged implementation
of ChokingManager lives in _choking_manager.py.
"""

from bittorrent_lite.scheduling.upload_policy import ProjectUploadPolicy  # noqa: F401
from bittorrent_lite.scheduling.legacy._choking_manager import ChokingManager

__all__ = ["ChokingManager", "ProjectUploadPolicy"]

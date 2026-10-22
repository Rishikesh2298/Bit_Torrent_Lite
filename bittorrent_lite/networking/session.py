"""
BitTorrent-Lite handshake compatibility module.

The actual Handshake message is defined in protocol.messages.
This module re-exports it so networking code can import Handshake
from protocol.handshake without creating a second incompatible type.
"""

from bittorrent_lite.networking.messages import Handshake

__all__ = ["Handshake"]
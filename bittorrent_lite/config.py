"""
BitTorrent-Lite: Configuration Constants

All tunable parameters for the system are defined here.
Import this module wherever you need configuration values.
No module should hardcode ports, sizes, or addresses.
"""

# ──────────────────────────────────────────────
# File & Piece Settings
# ──────────────────────────────────────────────
PIECE_SIZE = 65_536                   # 64 KiB per piece (in bytes)
HASH_ALGORITHM = "sha256"
MAX_FILE_SIZE = 67_108_864            # 64 MiB file-size limit for version 1

# ──────────────────────────────────────────────
# Tracker Settings
# ──────────────────────────────────────────────
TRACKER_HOST = "127.0.0.1"
TRACKER_PORT = 8000
TRACKER_PEER_TIMEOUT = 20             # seconds before a peer entry expires
ANNOUNCE_INTERVAL = 5                 # seconds between periodic tracker announces
HTTP_TIMEOUT = 3                      # seconds for a single HTTP request
TRACKER_RETRY_DELAYS = [2, 4, 10]    # exponential-ish back-off on tracker failure (seconds)
MAX_ANNOUNCE_BODY = 4096              # bytes — upper bound on POST body from a peer

# ──────────────────────────────────────────────
# Peer Networking Settings
# ──────────────────────────────────────────────
PEER_HOST = "127.0.0.1"
PEER_PORT_RANGE_START = 9000          # peers pick ports from 9000+
MAX_CONNECTIONS = 10                  # hard cap on simultaneous peer connections
SOCKET_TIMEOUT = 30                   # seconds — general socket timeout
HANDSHAKE_TIMEOUT = 10                # seconds — deadline for handshake exchange

# ──────────────────────────────────────────────
# Protocol Settings
# ──────────────────────────────────────────────
PROTOCOL_NAME = "BitTorrent-Lite"     # string — appears in HANDSHAKE JSON header
PROTOCOL_VERSION = 1                  # integer — protocol version for forward compat
MAX_HEADER_SIZE = 16_384              # 16 KiB — upper bound on JSON header bytes

# ──────────────────────────────────────────────
# Piece Management / Scheduler Settings
# ──────────────────────────────────────────────
MAX_OUTSTANDING_REQUESTS = 4          # pipeline window: concurrent requests per connection
REQUEST_TIMEOUT = 10                  # seconds before a request is considered timed out
QUEUE_SEND_TIMEOUT = 5                # seconds — max wait when enqueuing an outbound message

# ──────────────────────────────────────────────
# Upload / Choking Settings
# ──────────────────────────────────────────────
CHOKING_INTERVAL = 5                  # seconds between upload-slot recalculations
UNCHOKE_SLOTS = 2                     # number of peers allowed to receive uploads at a time
UPLOAD_QUEUE_CAP = 4                  # max queued upload jobs per connection

# ──────────────────────────────────────────────
# Paths (defaults — override via CLI args)
# ──────────────────────────────────────────────
DEFAULT_PIECES_DIR = "pieces"
DEFAULT_DOWNLOADS_DIR = "downloads"

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
LOG_LEVEL = "INFO"                    # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "[%(asctime)s] [%(name)-12s] %(levelname)-7s %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

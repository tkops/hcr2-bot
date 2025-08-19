VERSION = "0.2.0"

HISTORY = [
    ("0.2.0", "2025-08-19", "Base functions optimized"),
    ("0.1.1", "2025-07-30", "Nextcloud Integration"),
    ("0.1.0", "2025-07-15", "Initial version"),
]

def get_version():
    return VERSION

def get_history(limit=10):
    """Return version history as list of tuples (version, date, change)."""
    return HISTORY[:limit]


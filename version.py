VERSION = "0.3.2"

HISTORY = [
    ("0.3.3", "2025-08-22", "Fix bday help"),
    ("0.3.2", "2025-08-22", "Add birthday list"),
    ("0.3.1", "2025-08-22", "Update/Add some help messages"),
    ("0.3.0", "2025-08-22", "Plot stats and some optimizations"),
    ("0.2.0", "2025-08-19", "Base functions optimized"),
    ("0.1.1", "2025-07-30", "Nextcloud Integration"),
    ("0.1.0", "2025-07-15", "Initial version"),
]

def get_version():
    return VERSION

def get_history(limit=10):
    """Return version history as list of tuples (version, date, change)."""
    return HISTORY[:limit]


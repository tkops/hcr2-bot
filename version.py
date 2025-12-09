VERSION = "0.5.2"

HISTORY = [
    ("0.5.2", "2025-12-09", "Add score and points stats"),
    ("0.5.1", "2025-12-09", "Optimize perf stats"),
    ("0.5.0", "2025-12-03", "Add donations"),
    ("0.4.9", "2025-11-18", "Add stats per teamevent"),
    ("0.4.8", "2025-11-18", "Add match details to players profile"),
    ("0.4.7", "2025-10-25", "modify player list-active --team plte"),
    ("0.4.6", "2025-10-25", "Add player id edit to matchscore"),
    ("0.4.5", "2025-10-25", "Modify matchscore listings"),
    ("0.4.4", "2025-09-09", "Delete player sheet afer import"),
    ("0.4.3", "2025-09-09", "Export Player Table"),
    ("0.4.2", "2025-09-03", "Some Stats fixes"),
    ("0.4.1", "2025-08-23", "Add .gp user command, Add matchup result to sheet, some command improvements"),
    ("0.4.0", "2025-08-23", "User modifications by sheet import"),
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

def get_history(limit=5):
    """Return version history as list of tuples (version, date, change)."""
    return HISTORY[:limit]


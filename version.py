VERSION = "1.9.1"

HISTORY = [
    ("1.9.1", "2026-08-16", "Discord-Ausgabe wird bei Ueberlaenge aufgeteilt statt verworfen; km-Rangliste passt in eine Nachricht"),
    ("1.9.0", "2026-08-16", "chest-video: Wochen-Truhe auslesen, video chest apply, roster ohne Match"),
    ("1.8.0", "2026-08-16", "Wochenkilometer: distance-Entity, Bot-Befehl .km, Schnitt im Profil, video chest frames"),
    ("1.7.0", "2026-08-16", "Nextcloud in Unterordner gegliedert: Team-Event/S<nr>, Ladys, Donations, Wochen-Truhe; Skill team-video heisst jetzt player-video"),
    ("1.6.0", "2026-08-16", "Kader-Abgleich aus dem Team-Video: video player frames/apply aktualisiert GP, Namen, Zu- und Abgaenge"),
    ("1.5.0", "2026-08-16", "video apply meldet zusaetzlich Auffaelligkeiten: abweichende Namen, nicht gefahrene Spielerinnen und Score-Ausreisser"),
    ("1.4.2", "2026-08-16", "video apply pr\u00fcft zus\u00e4tzlich den Gegnernamen aus dem Videokopf gegen das Match"),
    ("1.4.1", "2026-08-16", "ffmpeg wird \u00fcber HCR2_FFMPEG, PATH und imageio-ffmpeg gesucht (HEVC-f\u00e4hig, ohne root)"),
    ("1.4.0", "2026-08-16", "Match-Video: Ergebnisse aus dem Endstand-Video auslesen und per 'video apply' in die DB schreiben"),
    ("1.3.0", "2026-08-11", "CLI exit codes, bot contract tests, UTC timestamps, error causes"),
    ("1.2.0", "2026-08-11", "Block deletes that would orphan result data"),
    ("1.1.0", "2026-08-11", "Apply player name changes from match sheet import"),
    ("1.0.3", "2026-06-21", "Add deploy workflow"),
    ("1.0.2", "2026-06-21", "Add version bump helper"),
    ("1.0.1", "2026-06-21", "Tighten add command argument parsing"),
    ("1.0.0", "2026-06-04", "Codex refactor"),
    ("0.7.1", "2026-04-07", "Fix seasons stats"),
    ("0.7.0", "2026-04-04", "Stats showing all members with more than 3 matches for seasons stats"),
    ("0.6.2", "2026-03-29", "Simplify match add"),
    ("0.6.1", "2026-02-03", "sheet(donations): display amounts in k on export and import as thousands"),
    ("0.6.0", "2025-12-09", "Add player stats"),
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

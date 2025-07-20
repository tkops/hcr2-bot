CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    alias TEXT,
    garage_power INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
, birthday TEXT, team TEXT);

CREATE TABLE IF NOT EXISTS vehicle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            shortname TEXT NOT NULL UNIQUE
        );


CREATE TABLE IF NOT EXISTS teamevent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    iso_year INTEGER NOT NULL,
    iso_week INTEGER NOT NULL,
    tracks INTEGER DEFAULT 4,
    max_score_per_track INTEGER DEFAULT 15000,
    UNIQUE(iso_year, iso_week)
);


CREATE TABLE IF NOT EXISTS teamevent_vehicle (
            teamevent_id INTEGER NOT NULL,
            vehicle_id INTEGER NOT NULL,
            PRIMARY KEY (teamevent_id, vehicle_id),
            FOREIGN KEY (teamevent_id) REFERENCES teamevent(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_id) REFERENCES vehicle(id) ON DELETE CASCADE
        );

CREATE TABLE IF NOT EXISTS season (
            number INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            start TEXT NOT NULL,
            division TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS match (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teamevent_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            start TEXT NOT NULL,
            opponent TEXT NOT NULL,
            FOREIGN KEY (teamevent_id) REFERENCES teamevent(id) ON DELETE CASCADE,
            FOREIGN KEY (season_number) REFERENCES season(number) ON DELETE CASCADE
        );

CREATE TABLE IF NOT EXISTS matchscore (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 75000),
            points INTEGER NOT NULL DEFAULT 0 CHECK(points BETWEEN 0 AND 300),
            UNIQUE (match_id, player_id),
            FOREIGN KEY (match_id) REFERENCES match(id) ON DELETE CASCADE,
            FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
        );


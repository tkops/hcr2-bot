-- Deleting a row must fail while dependent rows still exist, instead of
-- silently taking result data with it. SQLite cannot ALTER a foreign key
-- clause, so the three tables holding result data are rebuilt with
-- ON DELETE RESTRICT. teamevent_vehicle keeps CASCADE: it only maps which
-- vehicles appeared in an event and holds no results.
--
-- The runner applies this with PRAGMA foreign_keys=OFF, so existing orphans
-- survive the copy. RESTRICT is enforced from here on for new deletes only;
-- pre-existing violations still need manual cleanup (PRAGMA foreign_key_check).
BEGIN;

CREATE TABLE donation_new(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    total INTEGER NOT NULL CHECK(total >= 0),
    UNIQUE (player_id, date),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE RESTRICT
);
INSERT INTO donation_new (id, player_id, date, total)
    SELECT id, player_id, date, total FROM donation;
DROP TABLE donation;
ALTER TABLE donation_new RENAME TO donation;

CREATE TABLE match_new(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teamevent_id INTEGER NOT NULL,
    season_number INTEGER NOT NULL,
    start TEXT NOT NULL,
    opponent TEXT NOT NULL,
    score_ladys INTEGER DEFAULT 0,
    score_opponent INTEGER DEFAULT 0,
    FOREIGN KEY (teamevent_id) REFERENCES teamevent(id) ON DELETE RESTRICT,
    FOREIGN KEY (season_number) REFERENCES season(number) ON DELETE RESTRICT
);
INSERT INTO match_new (id, teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
    SELECT id, teamevent_id, season_number, start, opponent, score_ladys, score_opponent FROM match;
DROP TABLE match;
ALTER TABLE match_new RENAME TO match;

CREATE TABLE matchscore_new(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 75000),
    points INTEGER NOT NULL DEFAULT 0 CHECK(points BETWEEN 0 AND 300),
    absent INTEGER CHECK(absent IN (0,1)),
    checkin INTEGER CHECK(checkin IN (0,1)),
    UNIQUE (match_id, player_id),
    FOREIGN KEY (match_id) REFERENCES match(id) ON DELETE RESTRICT,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE RESTRICT
);
INSERT INTO matchscore_new (id, match_id, player_id, score, points, absent, checkin)
    SELECT id, match_id, player_id, score, points, absent, checkin FROM matchscore;
DROP TABLE matchscore;
ALTER TABLE matchscore_new RENAME TO matchscore;

COMMIT;

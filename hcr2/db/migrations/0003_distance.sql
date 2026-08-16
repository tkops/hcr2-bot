-- Weekly kilometres per player, read from the team distance chest screen.
--
-- One row per player and ISO week, holding that week's distance - not a running
-- total like `donation`. The chest resets every period, so the value in the video
-- already is the week's performance, and an average over the last weeks is what
-- the team looks at.
--
-- ON DELETE RESTRICT for the same reason as matchscore and donation: this is
-- result data, and deleting a player must not take it along silently.
CREATE TABLE IF NOT EXISTS distance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    year INTEGER NOT NULL CHECK(year >= 2020),
    week INTEGER NOT NULL CHECK(week BETWEEN 1 AND 53),
    km INTEGER NOT NULL CHECK(km >= 0),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (player_id, year, week),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_distance_week ON distance(year, week);
CREATE INDEX IF NOT EXISTS idx_distance_player ON distance(player_id);

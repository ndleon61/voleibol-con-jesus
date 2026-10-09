-- Fresh installations only: the guarded CLI rejects any existing application objects.
CREATE TABLE teams (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE jornadas (
    id SERIAL PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE CHECK (number > 0)
);
CREATE TABLE matches (
    id SERIAL PRIMARY KEY,
    jornada_id INTEGER NOT NULL REFERENCES jornadas(id) ON DELETE RESTRICT,
    team1_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    team2_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    match_time TIME NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    CHECK (team1_id <> team2_id)
);
CREATE TABLE match_sets (
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE RESTRICT,
    set_number INTEGER NOT NULL,
    team1_points INTEGER NOT NULL,
    team2_points INTEGER NOT NULL,
    PRIMARY KEY (match_id, set_number)
);

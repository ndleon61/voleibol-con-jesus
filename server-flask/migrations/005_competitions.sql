-- Put new tables beside the existing league, even when $user precedes public.
DO $$ DECLARE target TEXT; BEGIN
    SELECT n.nspname INTO target FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid='jornadas'::regclass;
    PERFORM set_config('search_path', quote_ident(target), true);
END $$;
LOCK TABLE teams, jornadas, matches, match_sets IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE IF NOT EXISTS seasons (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    start_date DATE,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','active','completed','archived')),
    legacy_key TEXT UNIQUE,
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS seasons_name_unique ON seasons (lower(btrim(name)));
CREATE TABLE IF NOT EXISTS tournaments (
    id SERIAL PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    start_date DATE,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','active','completed','archived')),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    legacy_key TEXT UNIQUE,
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date),
    CHECK (NOT is_public OR status = 'active')
);
CREATE UNIQUE INDEX IF NOT EXISTS tournaments_name_unique ON tournaments (season_id,lower(btrim(name)));
CREATE UNIQUE INDEX IF NOT EXISTS tournaments_one_public ON tournaments (is_public) WHERE is_public;
CREATE TABLE IF NOT EXISTS tournament_teams (
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE RESTRICT,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    PRIMARY KEY (tournament_id,team_id)
);

-- Seed once only; rerunning must not reactivate or restore removed registrations.
DO $$ DECLARE season INTEGER; tournament INTEGER; fresh BOOLEAN; BEGIN
    SELECT id INTO season FROM seasons WHERE legacy_key='original_league';
    IF season IS NULL THEN
        INSERT INTO seasons(name,status,legacy_key) VALUES ('Temporada original','active','original_league') RETURNING id INTO season;
    END IF;
    SELECT id INTO tournament FROM tournaments WHERE legacy_key='original_league';
    fresh := tournament IS NULL;
    IF fresh THEN
        INSERT INTO tournaments(season_id,name,status,is_public,legacy_key)
            VALUES (season,'Torneo original','active',NOT EXISTS(SELECT 1 FROM tournaments WHERE is_public),'original_league') RETURNING id INTO tournament;
    END IF;
    ALTER TABLE jornadas ADD COLUMN IF NOT EXISTS tournament_id INTEGER REFERENCES tournaments(id) ON DELETE RESTRICT;
    UPDATE jornadas SET tournament_id=tournament WHERE tournament_id IS NULL;
    EXECUTE format('ALTER TABLE jornadas ALTER COLUMN tournament_id SET DEFAULT %L',tournament);
    IF fresh THEN
        INSERT INTO tournament_teams SELECT tournament,id FROM teams ON CONFLICT DO NOTHING;
    END IF;
END $$;
ALTER TABLE jornadas ALTER COLUMN tournament_id SET NOT NULL;
-- Only the number-only uniqueness is replaced, not IDs or foreign keys.
DO $$ DECLARE item RECORD; BEGIN
    FOR item IN SELECT conname FROM pg_constraint WHERE conrelid='jornadas'::regclass AND contype='u'
        AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='jornadas'::regclass AND attname='number')]::smallint[] LOOP
        EXECUTE format('ALTER TABLE jornadas DROP CONSTRAINT %I',item.conname);
    END LOOP;
END $$;
DROP INDEX IF EXISTS jornadas_number_unique;
CREATE UNIQUE INDEX IF NOT EXISTS jornadas_tournament_number_unique ON jornadas(tournament_id,number);

-- Repair missing ID generators using resolved table OIDs, not current_schema().
DO $$ DECLARE item TEXT; sequence_name TEXT; BEGIN
    FOREACH item IN ARRAY ARRAY['teams','jornadas','matches'] LOOP
        sequence_name := item || '_competition_id_seq';
        IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid=item::regclass AND attname='id' AND NOT atthasdef AND attidentity='') THEN
            EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I OWNED BY %I.id',sequence_name,item);
            EXECUTE format('SELECT setval(%L,GREATEST(COALESCE((SELECT MAX(id) FROM %I),0),1), COALESCE((SELECT MAX(id)>0 FROM %I),false))',sequence_name,item,item);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN id SET DEFAULT nextval(%L)',item,sequence_name);
        END IF;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION assert_tournament_open(tournament INTEGER) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE state TEXT; season_state TEXT;
BEGIN
    SELECT t.status,s.status INTO state,season_state FROM tournaments t JOIN seasons s ON s.id=t.season_id WHERE t.id=tournament FOR SHARE OF t,s;
    IF state IS NULL THEN RAISE EXCEPTION 'No se encontró el torneo' USING ERRCODE='23503'; END IF;
    IF state IN ('completed','archived') OR season_state IN ('completed','archived') THEN
        RAISE EXCEPTION 'La competición está cerrada' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION guard_jornada_competition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM assert_tournament_open(OLD.tournament_id);
        IF TG_OP='UPDATE' AND NEW.tournament_id <> OLD.tournament_id THEN
            RAISE EXCEPTION 'La jornada debe conservar su torneo' USING ERRCODE='23514',CONSTRAINT='competition_ownership';
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    PERFORM assert_tournament_open(NEW.tournament_id);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS jornadas_competition_guard ON jornadas;
CREATE TRIGGER jornadas_competition_guard BEFORE INSERT OR UPDATE OR DELETE ON jornadas FOR EACH ROW EXECUTE FUNCTION guard_jornada_competition();

CREATE OR REPLACE FUNCTION guard_roster_competition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        PERFORM assert_tournament_open(OLD.tournament_id);
        IF EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=OLD.tournament_id AND OLD.team_id IN (m.team1_id,m.team2_id)) THEN
            RAISE EXCEPTION 'El equipo tiene partidos en el torneo' USING ERRCODE='23514',CONSTRAINT='roster_history';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Modifica la inscripción mediante alta o baja' USING ERRCODE='23514'; END IF;
    PERFORM assert_tournament_open(NEW.tournament_id);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS roster_competition_guard ON tournament_teams;
CREATE TRIGGER roster_competition_guard BEFORE INSERT OR UPDATE OR DELETE ON tournament_teams FOR EACH ROW EXECUTE FUNCTION guard_roster_competition();

CREATE OR REPLACE FUNCTION guard_match_competition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE tournament INTEGER; begins DATE; ends DATE; local_date DATE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT tournament_id INTO tournament FROM jornadas WHERE id=OLD.jornada_id;
        PERFORM assert_tournament_open(tournament);
        IF TG_OP='UPDATE' AND NEW.jornada_id <> OLD.jornada_id THEN
            RAISE EXCEPTION 'El partido debe conservar su jornada' USING ERRCODE='23514',CONSTRAINT='competition_ownership';
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    SELECT tournament_id INTO tournament FROM jornadas WHERE id=NEW.jornada_id;
    PERFORM assert_tournament_open(tournament);
    PERFORM team_id FROM tournament_teams WHERE tournament_id=tournament AND team_id IN(NEW.team1_id,NEW.team2_id) ORDER BY team_id FOR SHARE;
    IF (SELECT COUNT(*) FROM tournament_teams WHERE tournament_id=tournament AND team_id IN(NEW.team1_id,NEW.team2_id)) <> 2 THEN
        RAISE EXCEPTION 'Los equipos deben estar inscritos en el torneo' USING ERRCODE='23514',CONSTRAINT='competition_roster';
    END IF;
    SELECT start_date,end_date INTO begins,ends FROM tournaments WHERE id=tournament;
    local_date := (NEW.scheduled_at AT TIME ZONE 'America/Havana')::date;
    IF local_date < begins OR local_date > ends THEN
        RAISE EXCEPTION 'La fecha está fuera del torneo' USING ERRCODE='23514',CONSTRAINT='competition_dates';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION guard_season_details() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status='active' AND NEW.status='planned' THEN
        RAISE EXCEPTION 'La temporada ya está en curso' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
    IF OLD.status IN('completed','archived') AND
        ((NEW.name,NEW.start_date,NEW.end_date) IS DISTINCT FROM(OLD.name,OLD.start_date,OLD.end_date)
         OR (OLD.status='archived' AND NEW.status<>'archived') OR NEW.status NOT IN('completed','archived')) THEN
        RAISE EXCEPTION 'La temporada está cerrada' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
    IF NEW.status IN('completed','archived') AND EXISTS(SELECT 1 FROM tournaments WHERE season_id=OLD.id AND status NOT IN('completed','archived')) THEN
        RAISE EXCEPTION 'Hay torneos abiertos' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
    IF EXISTS(SELECT 1 FROM tournaments WHERE season_id=OLD.id AND
        ((NEW.start_date IS NOT NULL AND (start_date IS NULL OR start_date<NEW.start_date)) OR (NEW.end_date IS NOT NULL AND (end_date IS NULL OR end_date>NEW.end_date)))) THEN
        RAISE EXCEPTION 'Las fechas no incluyen los torneos' USING ERRCODE='23514',CONSTRAINT='competition_dates';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS seasons_details_guard ON seasons;
CREATE TRIGGER seasons_details_guard BEFORE UPDATE ON seasons FOR EACH ROW EXECUTE FUNCTION guard_season_details();

CREATE OR REPLACE FUNCTION guard_tournament_details() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent seasons; BEGIN
    SELECT * INTO parent FROM seasons WHERE id=NEW.season_id FOR SHARE;
    IF TG_OP='UPDATE' THEN
        IF OLD.status='active' AND NEW.status='planned' THEN RAISE EXCEPTION 'El torneo ya está en curso' USING ERRCODE='23514',CONSTRAINT='competition_closed'; END IF;
        IF NEW.season_id<>OLD.season_id THEN RAISE EXCEPTION 'El torneo debe conservar su temporada' USING ERRCODE='23514',CONSTRAINT='competition_ownership'; END IF;
        IF OLD.status IN('completed','archived') AND
            ((NEW.name,NEW.start_date,NEW.end_date,NEW.is_public) IS DISTINCT FROM(OLD.name,OLD.start_date,OLD.end_date,OLD.is_public)
             OR (OLD.status='archived' AND NEW.status<>'archived') OR NEW.status NOT IN('completed','archived')) THEN
            RAISE EXCEPTION 'El torneo está cerrado' USING ERRCODE='23514',CONSTRAINT='competition_closed';
        END IF;
    END IF;
    IF parent.status IN('completed','archived') AND NOT (TG_OP='UPDATE' AND OLD.status='completed' AND NEW.status='archived') THEN
        RAISE EXCEPTION 'La temporada está cerrada' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
    IF (parent.start_date IS NOT NULL AND (NEW.start_date IS NULL OR NEW.start_date<parent.start_date)) OR
        (parent.end_date IS NOT NULL AND (NEW.end_date IS NULL OR NEW.end_date>parent.end_date)) OR
        EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=NEW.id AND
            ((m.scheduled_at AT TIME ZONE 'America/Havana')::date<NEW.start_date OR (m.scheduled_at AT TIME ZONE 'America/Havana')::date>NEW.end_date)) THEN
        RAISE EXCEPTION 'Las fechas de la competición no son coherentes' USING ERRCODE='23514',CONSTRAINT='competition_dates';
    END IF;
    IF NEW.status='completed' AND EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=NEW.id AND m.status<>'finished') THEN
        RAISE EXCEPTION 'Hay partidos pendientes' USING ERRCODE='23514',CONSTRAINT='competition_closed';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tournaments_details_guard ON tournaments;
CREATE TRIGGER tournaments_details_guard BEFORE INSERT OR UPDATE ON tournaments FOR EACH ROW EXECUTE FUNCTION guard_tournament_details();
DROP TRIGGER IF EXISTS matches_competition_guard ON matches;
CREATE TRIGGER matches_competition_guard BEFORE INSERT OR UPDATE OR DELETE ON matches FOR EACH ROW EXECUTE FUNCTION guard_match_competition();

CREATE OR REPLACE FUNCTION guard_results_competition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE tournament INTEGER; BEGIN
    IF TG_OP<>'INSERT' THEN
        SELECT j.tournament_id INTO tournament FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE m.id=OLD.match_id;
        IF tournament IS NOT NULL THEN PERFORM assert_tournament_open(tournament); END IF;
        IF TG_OP='UPDATE' AND NEW.match_id<>OLD.match_id THEN
            RAISE EXCEPTION 'El resultado debe conservar su partido' USING ERRCODE='23514',CONSTRAINT='competition_ownership';
        END IF;
    END IF;
    IF TG_OP<>'DELETE' THEN
        SELECT j.tournament_id INTO tournament FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE m.id=NEW.match_id;
        IF tournament IS NOT NULL THEN PERFORM assert_tournament_open(tournament); END IF;
    END IF;
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
DROP TRIGGER IF EXISTS results_competition_guard ON match_sets;
CREATE TRIGGER results_competition_guard BEFORE INSERT OR UPDATE OR DELETE ON match_sets FOR EACH ROW EXECUTE FUNCTION guard_results_competition();

-- Same conflict rules as phase 6, now confined to the owning tournament.
CREATE OR REPLACE FUNCTION check_match_schedule() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE tournament INTEGER;
BEGIN
    IF TG_OP='UPDATE' AND (NEW.team1_id,NEW.team2_id,NEW.jornada_id,NEW.scheduled_at,NEW.match_time,NEW.duration_minutes)
        IS NOT DISTINCT FROM (OLD.team1_id,OLD.team2_id,OLD.jornada_id,OLD.scheduled_at,OLD.match_time,OLD.duration_minutes) THEN RETURN NEW; END IF;
    IF NEW.scheduled_at IS NULL THEN RETURN NEW; END IF;
    SELECT tournament_id INTO tournament FROM jornadas WHERE id=NEW.jornada_id;
    PERFORM id FROM teams WHERE id IN(NEW.team1_id,NEW.team2_id) ORDER BY id FOR UPDATE;
    IF EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=tournament AND m.id<>NEW.id
        AND LEAST(m.team1_id,m.team2_id)=LEAST(NEW.team1_id,NEW.team2_id) AND GREATEST(m.team1_id,m.team2_id)=GREATEST(NEW.team1_id,NEW.team2_id)
        AND (m.scheduled_at=NEW.scheduled_at OR (m.scheduled_at IS NULL AND m.jornada_id=NEW.jornada_id AND m.match_time=NEW.match_time))) THEN
        RAISE EXCEPTION 'El partido ya existe' USING ERRCODE='23505',CONSTRAINT='matches_fixture_duplicate';
    END IF;
    IF EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id
        CROSS JOIN LATERAL(SELECT COALESCE(m.scheduled_at,(((NEW.scheduled_at AT TIME ZONE 'America/Havana')::date+m.match_time) AT TIME ZONE 'America/Havana')) starts) s
        WHERE j.tournament_id=tournament AND m.id<>NEW.id AND (m.team1_id IN(NEW.team1_id,NEW.team2_id) OR m.team2_id IN(NEW.team1_id,NEW.team2_id))
        AND (m.scheduled_at IS NOT NULL OR m.jornada_id=NEW.jornada_id)
        AND s.starts<NEW.scheduled_at+make_interval(mins=>NEW.duration_minutes) AND s.starts+make_interval(mins=>m.duration_minutes)>NEW.scheduled_at) THEN
        RAISE EXCEPTION 'Un equipo tiene otro partido en ese intervalo' USING ERRCODE='23P01',CONSTRAINT='matches_team_overlap';
    END IF;
    RETURN NEW;
END $$;

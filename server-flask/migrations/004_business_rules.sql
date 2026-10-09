LOCK TABLE matches, match_sets IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 120;

-- NOT VALID preserves historical records; new writes must meet these checks.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'matches'::regclass AND conname = 'matches_duration_valid') THEN
        ALTER TABLE matches ADD CONSTRAINT matches_duration_valid CHECK (duration_minutes BETWEEN 1 AND 1440) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'match_sets'::regclass AND conname = 'match_sets_values_valid') THEN
        ALTER TABLE match_sets ADD CONSTRAINT match_sets_values_valid
            CHECK (set_number BETWEEN 1 AND 5 AND team1_points >= 0 AND team2_points >= 0 AND team1_points <> team2_points) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'matches'::regclass AND conname = 'matches_time_consistent') THEN
        ALTER TABLE matches ADD CONSTRAINT matches_time_consistent
            CHECK (scheduled_at IS NULL OR match_time = (scheduled_at AT TIME ZONE 'America/Havana')::time) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION protect_match_history() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'finished' OR EXISTS (SELECT 1 FROM match_sets WHERE match_id = OLD.id) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'El partido tiene resultados registrados'
                USING ERRCODE = '23514', CONSTRAINT = 'matches_history_protected';
        END IF;
        IF (NEW.team1_id, NEW.team2_id, NEW.jornada_id) IS DISTINCT FROM (OLD.team1_id, OLD.team2_id, OLD.jornada_id)
            OR (OLD.status = 'finished' AND NEW.status <> 'finished') THEN
            RAISE EXCEPTION 'Se debe conservar el historial del partido'
                USING ERRCODE = '23514', CONSTRAINT = 'matches_history_protected';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

DROP TRIGGER IF EXISTS matches_history_guard ON matches;
CREATE TRIGGER matches_history_guard BEFORE DELETE OR UPDATE OF team1_id, team2_id, jornada_id, status
    ON matches FOR EACH ROW EXECUTE FUNCTION protect_match_history();

CREATE OR REPLACE FUNCTION check_match_schedule() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.team1_id, NEW.team2_id, NEW.jornada_id, NEW.scheduled_at, NEW.match_time, NEW.duration_minutes)
            IS NOT DISTINCT FROM (OLD.team1_id, OLD.team2_id, OLD.jornada_id, OLD.scheduled_at, OLD.match_time, OLD.duration_minutes) THEN
            RETURN NEW;
        END IF;
    END IF;
    -- No date is manufactured for unknown historical schedules.
    IF NEW.scheduled_at IS NULL THEN RETURN NEW; END IF;

    PERFORM id FROM teams WHERE id IN (NEW.team1_id, NEW.team2_id) ORDER BY id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM matches m WHERE m.id <> NEW.id
          AND LEAST(m.team1_id, m.team2_id) = LEAST(NEW.team1_id, NEW.team2_id)
          AND GREATEST(m.team1_id, m.team2_id) = GREATEST(NEW.team1_id, NEW.team2_id)
          AND (m.scheduled_at = NEW.scheduled_at OR
               (m.scheduled_at IS NULL AND m.jornada_id = NEW.jornada_id AND m.match_time = NEW.match_time))
    ) THEN
        RAISE EXCEPTION 'El partido ya existe'
            USING ERRCODE = '23505', CONSTRAINT = 'matches_fixture_duplicate';
    END IF;

    IF EXISTS (
        SELECT 1 FROM matches m
        CROSS JOIN LATERAL (SELECT COALESCE(m.scheduled_at,
            (((NEW.scheduled_at AT TIME ZONE 'America/Havana')::date + m.match_time) AT TIME ZONE 'America/Havana')) AS starts) s
        WHERE m.id <> NEW.id
          AND (m.team1_id IN (NEW.team1_id, NEW.team2_id) OR m.team2_id IN (NEW.team1_id, NEW.team2_id))
          AND (m.scheduled_at IS NOT NULL OR m.jornada_id = NEW.jornada_id)
          AND s.starts < NEW.scheduled_at + make_interval(mins => NEW.duration_minutes)
          AND s.starts + make_interval(mins => m.duration_minutes) > NEW.scheduled_at
    ) THEN
        RAISE EXCEPTION 'Un equipo tiene otro partido en ese intervalo'
            USING ERRCODE = '23P01', CONSTRAINT = 'matches_team_overlap';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS matches_schedule_guard ON matches;
CREATE TRIGGER matches_schedule_guard BEFORE INSERT OR UPDATE OF team1_id, team2_id, jornada_id, scheduled_at, match_time, duration_minutes
    ON matches FOR EACH ROW EXECUTE FUNCTION check_match_schedule();

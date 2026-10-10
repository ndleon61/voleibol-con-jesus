LOCK TABLE matches, match_sets IN SHARE ROW EXCLUSIVE MODE;

-- Preserve the format of every existing match; only new matches default to three.
ALTER TABLE matches ADD COLUMN IF NOT EXISTS best_of INTEGER NOT NULL DEFAULT 5;
ALTER TABLE matches ALTER COLUMN best_of SET DEFAULT 3;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='matches'::regclass AND conname='matches_best_of_valid') THEN
        ALTER TABLE matches ADD CONSTRAINT matches_best_of_valid CHECK (best_of IN (3,5));
    END IF;
END $$;

CREATE OR REPLACE FUNCTION protect_match_format() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.best_of IS DISTINCT FROM OLD.best_of AND
        (OLD.status='finished' OR EXISTS (SELECT 1 FROM match_sets WHERE match_id=OLD.id)) THEN
        RAISE EXCEPTION 'No se puede cambiar el formato de un partido con resultados'
            USING ERRCODE='23514', CONSTRAINT='matches_history_protected';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS matches_format_guard ON matches;
CREATE TRIGGER matches_format_guard BEFORE UPDATE OF best_of ON matches
    FOR EACH ROW EXECUTE FUNCTION protect_match_format();

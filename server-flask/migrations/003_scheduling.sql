LOCK TABLE jornadas, matches IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;

-- Leave unknown historical dates NULL. Never manufacture a date or rewrite IDs.
DO $$
DECLARE
    table_name_value TEXT;
    sequence_name TEXT;
BEGIN
    FOREACH table_name_value IN ARRAY ARRAY['jornadas', 'matches'] LOOP
        sequence_name := table_name_value || '_scheduling_id_seq';
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = table_name_value
              AND column_name = 'id' AND column_default IS NULL AND is_identity = 'NO'
        ) THEN
            EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I OWNED BY %I.id', sequence_name, table_name_value);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN id SET DEFAULT nextval(%L)', table_name_value, sequence_name);
        END IF;
        IF to_regclass(sequence_name) IS NOT NULL THEN
            EXECUTE format('SELECT setval(%L, GREATEST(COALESCE((SELECT MAX(id) FROM %I), 0), (SELECT last_value FROM %I)), TRUE)', sequence_name, table_name_value, sequence_name);
        END IF;
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS jornadas_number_unique ON jornadas (number);
CREATE UNIQUE INDEX IF NOT EXISTS matches_schedule_unique
    ON matches (jornada_id, (LEAST(team1_id, team2_id)), (GREATEST(team1_id, team2_id)), scheduled_at)
    WHERE scheduled_at IS NOT NULL;

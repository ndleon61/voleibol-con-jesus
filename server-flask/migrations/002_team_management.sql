LOCK TABLE teams IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE teams ADD COLUMN IF NOT EXISTS logo_path TEXT;

-- The existing installation assigns team IDs manually. Add a generator only
-- when none exists, and keep every existing team ID and foreign key intact.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'teams'
          AND column_name = 'id' AND column_default IS NULL AND is_identity = 'NO'
    ) THEN
        CREATE SEQUENCE IF NOT EXISTS teams_management_id_seq OWNED BY teams.id;
        ALTER TABLE teams ALTER COLUMN id SET DEFAULT nextval('teams_management_id_seq');
    END IF;
    IF to_regclass('teams_management_id_seq') IS NOT NULL THEN
        PERFORM setval('teams_management_id_seq',
            GREATEST(COALESCE((SELECT MAX(id) FROM teams), 0),
                (SELECT last_value FROM teams_management_id_seq)), TRUE);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS teams_name_normalized_unique
    ON teams (lower(btrim(name)));

-- Preserve the existing logos while moving their ownership to the database.
-- Only newly added logo fields are seeded; rerunning the command does not
-- restore logos an administrator has intentionally removed.

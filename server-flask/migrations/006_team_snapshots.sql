-- Run through init-snapshots to materialize any legacy /media/ assets first.
DO $$ DECLARE target TEXT; BEGIN
    SELECT n.nspname INTO target FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid='tournament_teams'::regclass;
    PERFORM set_config('search_path',quote_ident(target),true);
END $$;
LOCK TABLE teams,tournaments,tournament_teams IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE tournament_teams ADD COLUMN IF NOT EXISTS team_name_snapshot TEXT;
ALTER TABLE tournament_teams ADD COLUMN IF NOT EXISTS team_logo_snapshot TEXT;
ALTER TABLE tournament_teams ADD COLUMN IF NOT EXISTS snapshot_created_at TIMESTAMPTZ;
DROP TRIGGER IF EXISTS roster_competition_guard ON tournament_teams;

CREATE OR REPLACE FUNCTION frozen_team_logo(team INTEGER, logo TEXT) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE result TEXT; BEGIN
    result := COALESCE(NULLIF(current_setting('voli.snapshot_logos',true),'')::jsonb->>team::text,logo,'');
    IF result<>'' AND result !~ '^/team-logos/[a-f0-9]{32}\.webp$' THEN
        RAISE EXCEPTION 'Preserva primero los logotipos locales' USING ERRCODE='23514',CONSTRAINT='snapshot_logo';
    END IF;
    RETURN result;
END $$;
UPDATE tournament_teams r SET
    team_name_snapshot=COALESCE(r.team_name_snapshot,t.name),
    team_logo_snapshot=COALESCE(r.team_logo_snapshot,frozen_team_logo(t.id,t.logo_path)),
    snapshot_created_at=COALESCE(r.snapshot_created_at,CURRENT_TIMESTAMP)
FROM teams t,tournaments c WHERE t.id=r.team_id AND c.id=r.tournament_id
    AND c.status IN('completed','archived')
    AND (r.team_name_snapshot IS NULL OR r.team_logo_snapshot IS NULL OR r.snapshot_created_at IS NULL);

CREATE OR REPLACE FUNCTION guard_roster_competition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN
        IF pg_trigger_depth()>1 AND OLD.snapshot_created_at IS NULL
           AND (OLD.team_name_snapshot IS NULL OR NEW.team_name_snapshot=OLD.team_name_snapshot)
           AND (OLD.team_logo_snapshot IS NULL OR NEW.team_logo_snapshot=OLD.team_logo_snapshot)
           AND NEW.team_id=OLD.team_id AND NEW.tournament_id=OLD.tournament_id
           AND NEW.team_name_snapshot IS NOT NULL AND NEW.team_logo_snapshot IS NOT NULL AND NEW.snapshot_created_at IS NOT NULL
           AND EXISTS(SELECT 1 FROM tournaments WHERE id=NEW.tournament_id AND status IN('completed','archived')) THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'La identidad histórica es inmutable' USING ERRCODE='23514',CONSTRAINT='snapshot_immutable';
    END IF;
    IF TG_OP='DELETE' THEN
        PERFORM assert_tournament_open(OLD.tournament_id);
        IF EXISTS(SELECT 1 FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=OLD.tournament_id AND OLD.team_id IN(m.team1_id,m.team2_id)) THEN
            RAISE EXCEPTION 'El equipo tiene partidos' USING ERRCODE='23514',CONSTRAINT='roster_history';
        END IF;
        RETURN OLD;
    END IF;
    PERFORM assert_tournament_open(NEW.tournament_id);
    IF NEW.team_name_snapshot IS NOT NULL OR NEW.team_logo_snapshot IS NOT NULL OR NEW.snapshot_created_at IS NOT NULL THEN
        RAISE EXCEPTION 'No se puede crear una identidad histórica manualmente' USING ERRCODE='23514',CONSTRAINT='snapshot_immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER roster_competition_guard BEFORE INSERT OR UPDATE OR DELETE ON tournament_teams FOR EACH ROW EXECUTE FUNCTION guard_roster_competition();

CREATE OR REPLACE FUNCTION capture_tournament_identity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IN('completed','archived') AND OLD.status NOT IN('completed','archived') THEN
        PERFORM t.id FROM teams t JOIN tournament_teams r ON r.team_id=t.id WHERE r.tournament_id=NEW.id ORDER BY t.id FOR SHARE OF t;
        UPDATE tournament_teams r SET team_name_snapshot=COALESCE(r.team_name_snapshot,t.name),
            team_logo_snapshot=COALESCE(r.team_logo_snapshot,frozen_team_logo(t.id,t.logo_path)),snapshot_created_at=CURRENT_TIMESTAMP
        FROM teams t WHERE r.team_id=t.id AND r.tournament_id=NEW.id AND r.snapshot_created_at IS NULL;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tournaments_snapshot_capture ON tournaments;
CREATE TRIGGER tournaments_snapshot_capture AFTER UPDATE OF status ON tournaments FOR EACH ROW EXECUTE FUNCTION capture_tournament_identity();

CREATE OR REPLACE VIEW tournament_team_identities AS
SELECT r.tournament_id,t.id,
    CASE WHEN c.status IN('completed','archived') THEN r.team_name_snapshot ELSE t.name END AS name,
    CASE WHEN c.status IN('completed','archived') THEN r.team_logo_snapshot ELSE t.logo_path END AS logo_path
FROM tournament_teams r JOIN teams t ON t.id=r.team_id JOIN tournaments c ON c.id=r.tournament_id;

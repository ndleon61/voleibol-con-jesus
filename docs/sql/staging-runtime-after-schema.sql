-- Prepared only. Run as voli_maintenance after approved schema initialization, not as runtime.
BEGIN;
DO $$ BEGIN
    IF current_database() <> 'voli_staging_2026' OR current_user <> 'voli_maintenance' THEN
        RAISE EXCEPTION 'Destino o rol incorrectos';
    END IF;
END $$;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO voli_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO voli_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO voli_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE voli_maintenance IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO voli_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE voli_maintenance IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO voli_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE voli_maintenance IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO voli_runtime;
COMMIT;
-- Read-only review: every flag must be false; membership must also be false.
SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls,
       pg_has_role('voli_runtime','neon_superuser','MEMBER') AS elevated_membership,
       pg_has_role('voli_runtime','voli_maintenance','MEMBER') AS maintenance_membership
FROM pg_roles WHERE rolname='voli_runtime';

-- Prepared only. Execute only with separate approval before fresh schema initialization.
-- Bind both passwords privately with psycopg.ClientCursor; never print the rendered SQL.
-- Supply plaintext passwords over verified TLS at LOGIN role creation;
-- PostgreSQL stores SCRAM hashes. This template contains no credential values.
BEGIN;
DO $$ BEGIN
    IF current_database() <> 'voli_staging_2026'
       OR current_setting('server_version_num')::integer NOT BETWEEN 180006 AND 189999 THEN
        RAISE EXCEPTION 'Destino o versión incorrectos';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
       OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
       OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_'
                 AND nspname NOT IN ('public','information_schema'))
       OR EXISTS(SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql') THEN
        RAISE EXCEPTION 'El destino debe estar vacío';
    END IF;
END $$;
SET LOCAL password_encryption = 'scram-sha-256';
CREATE ROLE voli_maintenance LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3 PASSWORD %(maintenance_password)s;
CREATE ROLE voli_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD %(runtime_password)s;
-- Allows the provisioning owner to assign schema ownership; never grant this to runtime.
GRANT voli_maintenance TO CURRENT_USER;
REVOKE CONNECT, TEMPORARY ON DATABASE voli_staging_2026 FROM PUBLIC;
GRANT CONNECT, CREATE ON DATABASE voli_staging_2026 TO voli_maintenance;
GRANT CONNECT ON DATABASE voli_staging_2026 TO voli_runtime;
ALTER SCHEMA public OWNER TO voli_maintenance;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO voli_runtime;
COMMIT;
-- Existing roles cause CREATE to fail; never reset existing credentials as a retry.

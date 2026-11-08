#!/bin/sh
# Creates the application role used at runtime. It has NO BYPASSRLS, so Row-Level Security applies
# to every tenant query. The owner role (POSTGRES_USER) runs migrations and admin/system jobs.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  DO \$\$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smsflow_app') THEN
      CREATE ROLE smsflow_app LOGIN PASSWORD '${APP_DB_PASSWORD:-smsflow_app}' NOSUPERUSER NOBYPASSRLS;
    END IF;
  END \$\$;
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO smsflow_app;
  GRANT USAGE ON SCHEMA public TO smsflow_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO smsflow_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO smsflow_app;
EOSQL

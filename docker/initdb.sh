#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 --set=app_password="$MEMORY_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
SELECT format('CREATE ROLE memory_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'app_password') \gexec
GRANT CONNECT ON DATABASE agent_memory TO memory_app;
GRANT USAGE, CREATE ON SCHEMA public TO memory_app;
SQL

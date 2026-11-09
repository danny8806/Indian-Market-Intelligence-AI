#!/bin/sh
# Runs once on the first initialization of the isolated PostgreSQL volume.
set -eu
: "${NEWS_WRITER_PASSWORD:?}"
: "${NEWS_READER_PASSWORD:?}"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ON_ERROR_STOP=1 \
  -v writer_password="$NEWS_WRITER_PASSWORD" \
  -v reader_password="$NEWS_READER_PASSWORD" <<'SQL'
CREATE ROLE news_writer LOGIN PASSWORD :'writer_password';
CREATE ROLE news_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE market_news TO news_writer, news_reader;
GRANT USAGE, CREATE ON SCHEMA public TO news_writer;
GRANT USAGE ON SCHEMA public TO news_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO news_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE news_writer IN SCHEMA public
  GRANT SELECT ON TABLES TO news_reader;
SQL

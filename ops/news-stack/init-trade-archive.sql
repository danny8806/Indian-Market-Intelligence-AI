\set ON_ERROR_STOP on
\getenv trade_archive_password TRADE_ARCHIVE_PASSWORD
SELECT format('CREATE ROLE trade_archive_writer LOGIN PASSWORD %L', :'trade_archive_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trade_archive_writer') \gexec
GRANT CONNECT ON DATABASE market_news TO trade_archive_writer;
CREATE SCHEMA IF NOT EXISTS trade_archive AUTHORIZATION trade_archive_writer;
REVOKE ALL ON SCHEMA trade_archive FROM PUBLIC;

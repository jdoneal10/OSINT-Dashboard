-- Runs once, on first initialization of the data volume.
-- The main database (osint) is created by POSTGRES_DB; add the test database.
CREATE DATABASE osint_test OWNER osint;

\connect osint
CREATE EXTENSION IF NOT EXISTS postgis;

\connect osint_test
CREATE EXTENSION IF NOT EXISTS postgis;

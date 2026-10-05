-- Schema for records.
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL DEFAULT 'a;b'
);

/* index */
CREATE UNIQUE INDEX idx_users_name ON users(name);

create or replace view active_users as
  select * from users;

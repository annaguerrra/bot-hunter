"""Conexões com SQLite local e PostgreSQL persistente no Neon."""
import sqlite3
from contextlib import contextmanager


class PostgresConnection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, statement, parameters=()):
        import psycopg
        if statement == 'BEGIN IMMEDIATE':
            statement = 'SELECT pg_advisory_xact_lock(49120481)'
        statement = statement.replace('?', '%s')
        try:
            return self.raw.execute(statement, parameters) if parameters else self.raw.execute(statement)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError('Constraint violation') from None

    def executemany(self, statement, parameters):
        for row in parameters:
            self.execute(statement, row)

    def insert_id(self, statement, parameters):
        return self.execute(statement + ' RETURNING id', parameters).fetchone()['id']


@contextmanager
def connection(path, database_url=''):
    if database_url:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=15, prepare_threshold=None) as raw:
            yield PostgresConnection(raw)
    else:
        db = sqlite3.connect(path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()


def insert_id(db, statement, parameters):
    if isinstance(db, PostgresConnection):
        return db.insert_id(statement, parameters)
    return db.execute(statement, parameters).lastrowid

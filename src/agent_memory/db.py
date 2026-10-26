from contextlib import contextmanager
from pathlib import Path

from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, url):
        self.pool = ConnectionPool(
            url, min_size=1, max_size=12, open=False,
            kwargs={"row_factory": dict_row}, configure=self._configure,
        )

    @staticmethod
    def _configure(conn):
        register_vector(conn)
        conn.commit()

    def open(self):
        self.pool.open(wait=True)
        with self.pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(8174261)")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)")
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                if not conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=%s", (path.name,)
                ).fetchone():
                    conn.execute(path.read_text())
                    conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))

    def close(self):
        self.pool.close()

    @contextmanager
    def transaction(self, owner):
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("SELECT set_config('memory.owner_id', %s, true)", (str(owner),))
                yield conn

"""
db.py — MySQL connection helper for Hawk Sight AI

Provides a single point of access to MySQL (XAMPP) using mysql-connector-python.
Uses a connection pool for efficiency and per-request connections to avoid
the SQLite-style "connection per request" mess.

Why a pool? Opening a fresh MySQL connection takes ~10-50ms. Under load,
that adds up fast. The pool keeps connections warm and hands them out.
"""

import os
from contextlib import contextmanager
from mysql.connector import pooling, Error as MySQLError
from dotenv import load_dotenv

load_dotenv()

# --- Connection pool (created once, shared across requests) ---
_pool = None


def get_pool():
    """Lazy-init the connection pool on first use."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="hawk_sight_pool",
            pool_size=10,
            pool_reset_session=True,
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "hawk_sight"),
            autocommit=False,  # We control transactions explicitly
            charset="utf8mb4",
        )
    return _pool


@contextmanager
def get_db(dict_cursor=True):
    """
    Context manager for a database connection.

    Usage:
        with get_db() as (conn, cursor):
            cursor.execute("SELECT ...")
            rows = cursor.fetchall()
            conn.commit()  # for writes

    Auto-rolls-back on exception, auto-closes connection.
    """
    conn = get_pool().get_connection()
    cursor = conn.cursor(dictionary=dict_cursor)
    try:
        yield conn, cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()  # Returns to pool, doesn't actually close


def init_db_check():
    """
    Sanity check on startup — verify all required tables exist.
    Don't auto-create them; user must run schema.sql in phpMyAdmin first.
    """
    required_tables = {"users", "portfolio", "favorites", "transactions", "autobuy_log"}
    try:
        with get_db(dict_cursor=False) as (conn, cursor):
            cursor.execute("SHOW TABLES")
            existing = {row[0] for row in cursor.fetchall()}
            missing = required_tables - existing
            if missing:
                raise RuntimeError(
                    f"Missing tables: {missing}. "
                    f"Run database/schema.sql in phpMyAdmin first."
                )
        print("✅ MySQL connected, all tables present.")
        return True
    except MySQLError as e:
        print(f"❌ MySQL connection failed: {e}")
        print(f"   Check: XAMPP MySQL running? Credentials in .env correct?")
        return False


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (table, column),
    )
    return cursor.fetchone()[0] > 0


def run_migrations():
    """
    Apply schema changes added after the initial schema.sql, idempotently.

    Lets an existing database (created before a column existed) upgrade itself
    on startup. MySQL 8 has no "ADD COLUMN IF NOT EXISTS", so we check
    information_schema first.
    """
    migrations = [
        # (table, column, ALTER statement to add it)
        ("users", "kill_switch_active",
         "ALTER TABLE users ADD COLUMN kill_switch_active BOOLEAN DEFAULT FALSE"),
    ]
    try:
        with get_db(dict_cursor=False) as (conn, cursor):
            for table, column, alter_sql in migrations:
                if not _column_exists(cursor, table, column):
                    cursor.execute(alter_sql)
                    conn.commit()
                    print(f"✅ Migration: added {table}.{column}")
    except MySQLError as e:
        print(f"⚠️  Migration check failed: {e}")

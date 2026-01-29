#!/usr/bin/env python3
"""
Migrate Evidence Browser from SQLite to PostgreSQL
"""
import sqlite3
import psycopg2
from psycopg2.extras import execute_batch
import sys

SQLITE_DB = "evidence.db"
POSTGRES_CONN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

def create_postgres_schema(pg_conn):
    """Create Evidence Browser schema in Postgres"""
    print("Creating Postgres schema...")
    
    with pg_conn.cursor() as cur:
        # Drop existing tables if they exist
        cur.execute("DROP TABLE IF EXISTS chat_messages CASCADE;")
        cur.execute("DROP TABLE IF EXISTS chat_threads CASCADE;")
        cur.execute("DROP TABLE IF EXISTS discoveries CASCADE;")
        cur.execute("DROP TABLE IF EXISTS file_index CASCADE;")
        cur.execute("DROP TABLE IF EXISTS device_category_counts CASCADE;")
        cur.execute("DROP TABLE IF EXISTS records CASCADE;")
        cur.execute("DROP TABLE IF EXISTS devices CASCADE;")
        
        # Create tables (Postgres-compatible versions)
        cur.execute("""
            CREATE TABLE devices (
                device_id TEXT PRIMARY KEY,
                name TEXT,
                type TEXT,
                owner TEXT,
                source TEXT
            );
        """)
        
        cur.execute("""
            CREATE TABLE records (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                category TEXT NOT NULL,
                timestamp TEXT,
                data TEXT NOT NULL,
                searchable TEXT NOT NULL
            );
            CREATE INDEX idx_device_cat ON records(device_id, category);
            CREATE INDEX idx_timestamp ON records(timestamp);
        """)
        
        cur.execute("""
            CREATE TABLE device_category_counts (
                device_id TEXT,
                category TEXT,
                count INTEGER,
                PRIMARY KEY (device_id, category)
            );
        """)
        
        cur.execute("""
            CREATE TABLE file_index (
                file_path TEXT PRIMARY KEY,
                mtime REAL,
                record_count INTEGER
            );
        """)
        
        cur.execute("""
            CREATE TABLE discoveries (
                id TEXT PRIMARY KEY,
                title TEXT,
                category TEXT,
                flames INTEGER,
                device_id TEXT,
                owner TEXT,
                content TEXT,
                timestamp TEXT,
                verified INTEGER DEFAULT 0,
                tags TEXT,
                data_type TEXT,
                source_app TEXT
            );
            CREATE INDEX idx_disc_flames ON discoveries(flames DESC);
            CREATE INDEX idx_disc_cat ON discoveries(category);
        """)
        
        cur.execute("""
            CREATE TABLE chat_threads (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                thread_num INTEGER NOT NULL,
                source_app TEXT,
                started TEXT,
                first_date TEXT,
                last_date TEXT,
                message_count INTEGER DEFAULT 0,
                participants TEXT,
                last_message_preview TEXT
            );
            CREATE INDEX idx_threads_device ON chat_threads(device_id);
        """)
        
        cur.execute("""
            CREATE TABLE chat_messages (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                thread_num INTEGER NOT NULL,
                timestamp TEXT,
                sender TEXT,
                body TEXT,
                source_app TEXT
            );
        """)
        
    pg_conn.commit()
    print("✅ Schema created")

def migrate_table(sqlite_conn, pg_conn, table_name, batch_size=1000):
    """Migrate a table from SQLite to Postgres"""
    print(f"Migrating {table_name}...")
    
    # Get all rows from SQLite
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f"SELECT * FROM {table_name}")
    
    # Get column names
    columns = [desc[0] for desc in sqlite_cur.description]
    
    # Prepare insert statement
    placeholders = ','.join(['%s'] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"
    
    # Batch insert
    pg_cur = pg_conn.cursor()
    rows = sqlite_cur.fetchall()
    total = len(rows)
    
    if total == 0:
        print(f"  No rows in {table_name}")
        return
    
    execute_batch(pg_cur, insert_sql, rows, page_size=batch_size)
    pg_conn.commit()
    
    print(f"  ✅ Migrated {total:,} rows")

def main():
    print("🔄 Evidence Browser SQLite → Postgres Migration")
    print("=" * 60)
    
    # Connect to both databases
    print("Connecting to databases...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    pg_conn = psycopg2.connect(POSTGRES_CONN)
    
    try:
        # Create schema
        create_postgres_schema(pg_conn)
        
        # Migrate tables in dependency order
        tables = [
            'devices',
            'records',
            'device_category_counts',
            'file_index',
            'discoveries',
            'chat_threads',
            'chat_messages'
        ]
        
        for table in tables:
            migrate_table(sqlite_conn, pg_conn, table)
        
        print("\n✅ Migration complete!")
        print("\nVerifying counts...")
        
        # Verify
        pg_cur = pg_conn.cursor()
        for table in tables:
            pg_cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = pg_cur.fetchone()[0]
            print(f"  {table}: {count:,} rows")
        
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    main()

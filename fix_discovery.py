#!/usr/bin/env python3
"""Fix discovery_engine.py for PostgreSQL"""
import re

# Read the file
with open('discovery_engine.py', 'r') as f:
    content = f.read()

# Replace imports
content = content.replace(
    'import sqlite3\nfrom collections import defaultdict',
    'from collections import defaultdict'
)
content = content.replace(
    'Works from SQLite records table for speed',
    'Works from PostgreSQL records table for speed'
)

# Add cursor at start of function
content = content.replace(
    'def scan_discoveries_from_db(conn, device_map):\n    """Scan discoveries from PostgreSQL records table. Much faster than re-parsing markdown."""\n    discoveries = list(VERIFIED_DISCOVERIES)',
    'def scan_discoveries_from_db(conn, device_map):\n    """Scan discoveries from PostgreSQL records table. Much faster than re-parsing markdown."""\n    cur = conn.cursor()\n    discoveries = list(VERIFIED_DISCOVERIES)'
)

# Replace all conn.execute with cur.execute
content = re.sub(r'\bconn\.execute\(', 'cur.execute(', content)

# Replace ? with %s and LIKE with ILIKE
content = re.sub(r'device_id=\?', 'device_id=%s', content)
content = re.sub(r'category=\?', 'category=%s', content)
content = re.sub(r'timestamp LIKE \?', 'timestamp LIKE %s', content)
content = re.sub(r'searchable LIKE \?', 'searchable ILIKE %s', content)

# Fix .fetchone()[0] patterns
content = re.sub(
    r'count = cur\.execute\(\s*"SELECT COUNT\(\*\) FROM',
    'cur.execute(\n            "SELECT COUNT(*) as count FROM',
    content
)
content = re.sub(r'pwd_count = cur\.execute\(\s*"SELECT COUNT\(\*\) FROM records WHERE device_id=%s AND category=\'passwords\'", \(device_id,\)\s*\)\.fetchone\(\)\[0\]',
    'cur.execute(\n            "SELECT COUNT(*) as count FROM records WHERE device_id=%s AND category=\'passwords\'", (device_id,)\n        )\n        pwd_count = cur.fetchone()[\'count\']',
    content
)
content = re.sub(r'\.fetchone\(\)\[0\]', '.fetchone()[\'count\']', content)

# Write the fixed content
with open('discovery_engine.py', 'w') as f:
    f.write(content)

print("Fixed discovery_engine.py for PostgreSQL")

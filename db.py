"""PostgreSQL-backed evidence index with full-text search.
Parses markdown once → stores in Postgres → serves from DB.
"""
import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
import os
import re
import json
import time
import logging
import threading
from pathlib import Path
from collections import defaultdict

_log = logging.getLogger('app')

POSTGRES_CONN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
CELLEBRITE_DIR = Path.home() / "clawd/tina-legal/cellebrite-parsed"
AXIOM_DIR = Path.home() / "clawd/rag/inbox/axiom-extracts"

DEVICE_MAP = {
    "belinda-knisley": {"name": "Belinda Knisley Phone", "type": "Phone", "owner": "Belinda Knisley"},
    "joy-quinn": {"name": "Joy Quinn iPhone", "type": "iPhone", "owner": "Joy Quinn"},
    "wendi-woods": {"name": "Wendi Woods iPhone", "type": "iPhone", "owner": "Wendi Woods"},
    "zachary-quinn": {"name": "Zachary Quinn Phone", "type": "Phone", "owner": "Zachary Quinn"},
}

AXIOM_DEVICE_MAP = {
    "RMR034359_White iPhone SE": {"owner": "Tina Peters", "type": "White iPhone SE"},
    "RMR034359_White iPhone SE_TaintClear": {"owner": "Tina Peters", "type": "White iPhone SE (TaintClear)"},
    "RMR034364_BlackiPhoneSE_TaintClear": {"owner": "Tina Peters", "type": "Black iPhone SE (TaintClear)"},
    "RMR034365_1stiPhone7_nonPriv": {"owner": "Tina Peters", "type": "iPhone 7"},
    "RMR034366_2ndiPhone7_nonPriv": {"owner": "Stephanie Wenholz", "type": "2nd iPhone 7"},
    "RMR034367_CompaqLaptop_TaintClear": {"owner": "Tina Peters", "type": "Compaq Laptop"},
    "RMR034371_Samsung_nonPriv": {"owner": "Sandra Brown", "type": "Samsung"},
    "RMR034371_Samsung_TaintClear": {"owner": "Sandra Brown", "type": "Samsung (TaintClear)"},
    "RMR034372 Motorola": {"owner": "Sandra Brown", "type": "Motorola"},
    "RMR034372_Motorola_TaintClear": {"owner": "Sandra Brown", "type": "Motorola (TaintClear)"},
    "RMR034373_LGTablet_NonPriv": {"owner": "Sandra Brown (unconfirmed)", "type": "LG Tablet"},
    "RMR034374_HPLaptop_NonPriv": {"owner": "Sandra Brown", "type": "HP Laptop (374)"},
    "RMR034375_ASUSLaptop_Non-Priv": {"owner": "Sandra Brown", "type": "ASUS Laptop (375)"},
    "RMR034376_HPDesktop": {"owner": "Wendi Woods", "type": "HP Desktop"},
    "RMR034376_HPDesktop_nonPriv": {"owner": "Wendi Woods", "type": "HP Desktop (nonPriv)"},
    "RMR034378_iPhone_nonPriv": {"owner": "Gerald Wood", "type": "iPhone"},
    "RMR034378_iPhoneTaintClear": {"owner": "Gerald Wood", "type": "iPhone (TaintClear)"},
    "RMR034379_BluPhone_nonPriv": {"owner": "Quinn Family (unconfirmed)", "type": "Blu Phone"},
    "RMR034381_ASUSLaptop_nonPriv": {"owner": "Quinn Family", "type": "ASUS Laptop (381)"},
    "RMR034382_MSILaptop_nonPriv": {"owner": "Wendi Woods", "type": "MSI Laptop"},
    "RMR034704_HPLaptop": {"owner": "Sherronna Bishop", "type": "HP Laptop"},
    "RMR034704_HPLaptop_nonPriv": {"owner": "Sherronna Bishop", "type": "HP Laptop (nonPriv)"},
    "RMR034705_LenovoAllinOne_nonPriv": {"owner": "Sherronna Bishop", "type": "Lenovo All-in-One"},
    "RMR035374_HPLaptop_TaintClear": {"owner": "Sandra Brown", "type": "HP Laptop (TaintClear)"},
    "RMR035375_ASUSLaptop_TaintClear": {"owner": "Sandra Brown", "type": "ASUS Laptop (TaintClear)"},
}

CATEGORIES = ["browsing", "calls", "chats", "contacts", "emails", "locations", "notes", "passwords", "searches", "voicemails"]

# Regex to extract base RMR number and device type from directory names
_RMR_RE = re.compile(r'^(RMR\d+)[_]?(.+?)(?:[_](?:TaintClear|taintclear|nonPriv|NonPriv|Non-Priv|non-priv))?$')

def _extract_rmr_base(device_id):
    """Extract base RMR number from device_id. Returns (rmr_number, base_type, extraction_suffix) or None."""
    m = re.match(r'^(RMR\d+)', device_id)
    if not m:
        return None
    rmr = m.group(1)
    rest = device_id[len(rmr):].lstrip('_')
    # Extract suffix
    suffix_match = re.search(r'[_]?(TaintClear|taintclear|nonPriv|NonPriv|Non-Priv|non-priv)$', rest)
    if suffix_match:
        suffix = suffix_match.group(1)
        base_type = rest[:suffix_match.start()].rstrip('_')
    else:
        suffix = ""
        base_type = rest
    return (rmr, base_type, suffix)

def _friendly_device_name(base_type, rmr):
    """Create a friendly name like 'HP Desktop (RMR034376)' from base_type."""
    name = base_type.replace('_', ' ').strip()
    # Clean up numbering suffixes like (374)
    name = re.sub(r'\s*\(\d+\)\s*$', '', name)
    return f"{name} ({rmr})" if name else rmr

# ─── Parsers (line-by-line, fast) ───

def _parse_chats(fpath):
    pat = re.compile(r'^- \[(\d{4}-\d{2}-\d{2}T[^\]]+)\] \*\*([^*]*)\*\*: (.+)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if not m:
            continue
        ts, sender, body = m.group(1), m.group(2), m.group(3).strip()
        idx = body.rfind('(')
        source = body[idx+1:-1] if idx > 0 and body.endswith(')') else ""
        if source:
            body = body[:idx].strip()
        yield {"timestamp": ts, "sender": sender, "body": body, "source_app": source}

def _parse_calls(fpath):
    pat = re.compile(r'^- \*\*(\d{4}-\d{2}-\d{2}T[^*]+)\*\* \| (\w+) \| (\w+) \| Duration: ([^ |]+)(.*)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if m:
            yield {"timestamp": m.group(1), "direction": m.group(2), "status": m.group(3), "duration": m.group(4), "details": m.group(5).strip(' |')}

def _parse_contacts(fpath):
    pat = re.compile(r'^- \*\*([^*]+)\*\* \| Source: (.+)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if m:
            yield {"name": m.group(1), "source_app": m.group(2).strip()}

def _parse_browsing(fpath):
    pat = re.compile(r'^- \*\*(\d{4}-\d{2}-\d{2}T[^*]+)\*\* \| \[([^\]]*)\]\(([^)]*)\) \| (.+)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if m:
            yield {"timestamp": m.group(1), "title": m.group(2), "url": m.group(3), "browser": m.group(4).strip()}

def _parse_searches(fpath):
    pat = re.compile(r'^- \*\*([^*]*)\*\* \| (.+?) \| (.+)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if m:
            yield {"timestamp": m.group(1), "query": m.group(2), "source_app": m.group(3).strip()}

def _parse_emails(fpath):
    lines = open(fpath, errors='replace').readlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('### ') and '—' in line:
            parts = line[4:].split('—', 1)
            ts = parts[0].strip()
            subject = parts[1].strip() if len(parts) > 1 else ""
            from_addr = to_addr = source = ""
            i += 1
            if i < len(lines):
                ft = re.match(r'\*\*From:\*\*\s*(.*?)\s*→\s*\*\*To:\*\*\s*(.*)', lines[i])
                if ft:
                    from_addr, to_addr = ft.group(1).strip(), ft.group(2).strip()
                i += 1
                if i < len(lines) and lines[i].startswith('**Source:**'):
                    source = lines[i].replace('**Source:**', '').strip()
                    i += 1
            preview = ""
            while i < len(lines) and not lines[i].startswith('---') and not lines[i].startswith('### '):
                clean = re.sub(r'<[^>]+>', '', lines[i]).strip()
                if clean and len(preview) < 300:
                    preview += clean + " "
                i += 1
            yield {"timestamp": ts, "subject": subject, "from_addr": from_addr, "to_addr": to_addr, "source_app": source, "preview": preview[:300].strip()}
        else:
            i += 1

def _parse_locations(fpath):
    pat = re.compile(r'^- \*\*([^*]*)\*\* \| ([^|]*)\|(.+)')
    for line in open(fpath, errors='replace'):
        m = pat.match(line)
        if m:
            rest = m.group(3).strip()
            parts = rest.split('|')
            addr = parts[0].strip() if len(parts) >= 2 else ""
            src = parts[1].strip() if len(parts) >= 2 else rest
            yield {"timestamp": m.group(1), "coords": m.group(2).strip(), "address": addr, "source_app": src}

def _parse_generic(fpath):
    for line in open(fpath, errors='replace'):
        line = line.strip()
        if line.startswith('- '):
            yield {"content": line[2:][:500]}

PARSERS = {
    "chats": _parse_chats, "calls": _parse_calls, "contacts": _parse_contacts,
    "browsing": _parse_browsing, "searches": _parse_searches, "emails": _parse_emails,
    "locations": _parse_locations, "notes": _parse_generic,
    "passwords": _parse_generic, "voicemails": _parse_generic,
}

# ─── Database ───

class EvidenceDB:
    def __init__(self):
        self._conn_pool = []
        self._lock = threading.Lock()
        self._stats_cache = None
        self._devices_cache = None
        self._discoveries_cache = None
        self._file_mtimes = {}
        self._last_index_time = 0
        self._rag_chunk_count = 0
        self._watcher_thread = None
        self._merged_device_map = {}

    def _get_conn(self):
        """Get a connection from the pool or create a new one."""
        return psycopg2.connect(POSTGRES_CONN, cursor_factory=RealDictCursor)

    def init_schema(self):
        """Schema already created by migration script."""
        pass

    def full_index(self, force=False):
        """Parse all data sources and load into Postgres.
        Skip if DB already has data (use force=True or POST /api/refresh to re-index)."""
        conn = self._get_conn()
        cur = conn.cursor()

        # Check if DB already populated
        try:
            cur.execute("SELECT COUNT(*) as count FROM records")
            count = cur.fetchone()['count']
            if count > 0 and not force:
                _log.info(f'DB already has {count:,} records, skipping full index')
                self._last_index_time = time.time()
                self._rag_chunk_count = self._get_rag_count()
                self._rebuild_caches()
                # Recompute discoveries if empty
                cur.execute("SELECT COUNT(*) as count FROM discoveries")
                disc_count = cur.fetchone()['count']
                if disc_count == 0:
                    self._compute_discoveries(conn)
                cur.close()
                conn.close()
                return
        except Exception:
            pass

        t0 = time.time()
        _log.info('Full index started')

        # Clear and rebuild
        cur.execute("DELETE FROM records")
        cur.execute("DELETE FROM devices")
        cur.execute("DELETE FROM device_category_counts")
        cur.execute("DELETE FROM file_index")
        cur.execute("DELETE FROM chat_threads")
        cur.execute("DELETE FROM chat_messages")

        # Index Cellebrite
        self._index_cellebrite(conn)
        # Index AXIOM metadata
        self._index_axiom_metadata(conn)
        
        conn.commit()

        # Compute discoveries
        self._compute_discoveries(conn)

        # Set timing first, then rebuild caches
        self._last_index_time = time.time()
        self._rag_chunk_count = self._get_rag_count()
        self._rebuild_caches()

        dt = time.time() - t0
        cur.execute("SELECT COUNT(*) as count FROM records")
        total = cur.fetchone()['count']
        _log.info(f'Full index complete: {total:,} records in {dt:.1f}s')
        
        cur.close()
        conn.close()

    def _index_cellebrite(self, conn):
        cur = conn.cursor()
        for person_id, info in DEVICE_MAP.items():
            cur.execute("INSERT INTO devices VALUES (%s,%s,%s,%s,%s) ON CONFLICT (device_id) DO UPDATE SET name=EXCLUDED.name",
                      (person_id, info["name"], info["type"], info["owner"], "cellebrite"))
            for cat in CATEGORIES:
                fpath = CELLEBRITE_DIR / f"{person_id}_{cat}.md"
                if not fpath.exists():
                    continue
                parser = PARSERS.get(cat, _parse_generic)
                count = 0
                batch = []
                for rec in parser(fpath):
                    data_json = json.dumps(rec, ensure_ascii=False)
                    # Build searchable text from all values
                    searchable = " ".join(str(v) for v in rec.values() if v)
                    ts = rec.get("timestamp", "")
                    batch.append((person_id, cat, ts, data_json, searchable))
                    count += 1
                    if len(batch) >= 5000:
                        execute_batch(cur, "INSERT INTO records (device_id,category,timestamp,data,searchable) VALUES (%s,%s,%s,%s,%s)", batch)
                        batch = []
                if batch:
                    execute_batch(cur, "INSERT INTO records (device_id,category,timestamp,data,searchable) VALUES (%s,%s,%s,%s,%s)", batch)
                cur.execute("INSERT INTO device_category_counts VALUES (%s,%s,%s) ON CONFLICT (device_id, category) DO UPDATE SET count=EXCLUDED.count",
                           (person_id, cat, count))
                cur.execute("INSERT INTO file_index VALUES (%s,%s,%s) ON CONFLICT (file_path) DO UPDATE SET mtime=EXCLUDED.mtime, record_count=EXCLUDED.record_count",
                           (str(fpath), fpath.stat().st_mtime, count))
                if count:
                    _log.debug(f'{person_id}/{cat}: {count}')
                # Parse chat threads
                if cat == 'chats':
                    self._index_chat_threads(conn, person_id, fpath)
        conn.commit()

    def _index_axiom_metadata(self, conn):
        cur = conn.cursor()
        if not AXIOM_DIR.exists():
            return
        for dirname in sorted(os.listdir(AXIOM_DIR)):
            dirpath = AXIOM_DIR / dirname
            if not dirpath.is_dir():
                continue
            info = AXIOM_DEVICE_MAP.get(dirname, {"owner": "Unknown", "type": dirname})
            cur.execute("INSERT INTO devices VALUES (%s,%s,%s,%s,%s) ON CONFLICT (device_id) DO UPDATE SET name=EXCLUDED.name",
                      (dirname, dirname, info["type"], info["owner"], "axiom"))
            total = 0
            for jf in dirpath.glob("*.json"):
                fsize = jf.stat().st_size
                est = max(1, fsize // 500)
                cur.execute("INSERT INTO device_category_counts VALUES (%s,%s,%s) ON CONFLICT (device_id,category) DO UPDATE SET count=EXCLUDED.count",
                           (dirname, jf.stem, est))
                total += est
            cur.execute("INSERT INTO file_index VALUES (%s,%s,%s) ON CONFLICT (file_path) DO UPDATE SET mtime=EXCLUDED.mtime, record_count=EXCLUDED.record_count",
                      (str(dirpath), dirpath.stat().st_mtime, total))
        conn.commit()

    def _index_chat_threads(self, conn, device_id, fpath):
        """Parse chat file into threads and store in DB."""
        cur = conn.cursor()
        header_pat = re.compile(r'^### Chat: (.+)')
        started_pat = re.compile(r'^\*\*Started:\*\* (.+)')
        msg_pat = re.compile(r'^- \[(\d{4}-\d{2}-\d{2}T[^\]]+)\] \*\*([^*]*)\*\*: (.+)')

        threads = []  # list of {source, started, messages: [{ts,sender,body,source_app}], participants: set}
        current = None
        thread_num = 0

        for line in open(fpath, errors='replace'):
            hm = header_pat.match(line)
            if hm:
                if current and current['messages']:
                    threads.append(current)
                thread_num += 1
                current = {'thread_num': thread_num, 'source': hm.group(1).strip(), 'started': '', 'messages': [], 'participants': set()}
                continue
            if current is not None:
                sm = started_pat.match(line)
                if sm:
                    current['started'] = sm.group(1).strip()
                    continue
            mm = msg_pat.match(line)
            if mm:
                ts, sender, body = mm.group(1), mm.group(2), mm.group(3).strip()
                idx = body.rfind('(')
                source_app = body[idx+1:-1] if idx > 0 and body.endswith(')') else ""
                if source_app:
                    body = body[:idx].strip()
                if current is None:
                    thread_num += 1
                    current = {'thread_num': thread_num, 'source': source_app or 'Unknown', 'started': ts, 'messages': [], 'participants': set()}
                current['messages'].append({'timestamp': ts, 'sender': sender, 'body': body, 'source_app': source_app})
                if sender:
                    current['participants'].add(sender)

        if current and current['messages']:
            threads.append(current)

        # Store threads
        thread_batch = []
        msg_batch = []
        for t in threads:
            msgs = t['messages']
            participants = list(t['participants']) or ['Unknown']
            first_date = msgs[0]['timestamp'] if msgs else t.get('started', '')
            last_date = msgs[-1]['timestamp'] if msgs else first_date
            last_preview = msgs[-1]['body'][:200] if msgs else ''
            thread_batch.append((device_id, t['thread_num'], t['source'], t.get('started', ''),
                                 first_date, last_date, len(msgs), json.dumps(participants), last_preview))
            for m in msgs:
                msg_batch.append((device_id, t['thread_num'], m['timestamp'], m['sender'], m['body'], m['source_app']))

        if thread_batch:
            execute_batch(cur, "INSERT INTO chat_threads (device_id,thread_num,source_app,started,first_date,last_date,message_count,participants,last_message_preview) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", thread_batch)
        if msg_batch:
            execute_batch(cur, "INSERT INTO chat_messages (device_id,thread_num,timestamp,sender,body,source_app) VALUES (%s,%s,%s,%s,%s,%s)", msg_batch)
        _log.debug(f'{device_id}/chat-threads: {len(threads)} threads, {len(msg_batch)} messages')

    def get_chat_threads(self, device_id, page=1, per_page=50, search=None, date_from=None, date_to=None):
        conn = self._get_conn()
        cur = conn.cursor()
        sub_ids = self._resolve_device_ids(device_id)
        placeholders = ",".join(["%s"] * len(sub_ids))
        where = [f"device_id IN ({placeholders})"]
        params = list(sub_ids)
        if date_from:
            where.append("last_date >= %s")
            params.append(date_from)
        if date_to:
            where.append("first_date <= %s")
            params.append(date_to + 'T23:59:59')
        if search:
            where.append("(participants LIKE %s OR last_message_preview LIKE %s OR source_app LIKE %s)")
            sl = f"%{search}%"
            params.extend([sl, sl, sl])
        where_sql = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) as count FROM chat_threads WHERE {where_sql}", params)
        total = cur.fetchone()['count']
        offset = (page - 1) * per_page
        cur.execute(f"SELECT * FROM chat_threads WHERE {where_sql} ORDER BY last_date DESC LIMIT %s OFFSET %s",
                         params + [per_page, offset])
        rows = cur.fetchall()
        threads = []
        for r in rows:
            threads.append({
                'thread_id': r['thread_num'],
                'source': r['source_app'] or 'Unknown',
                'participants': json.loads(r['participants']) if r['participants'] else ['Unknown'],
                'message_count': r['message_count'],
                'first_date': r['first_date'],
                'last_date': r['last_date'],
                'last_message_preview': r['last_message_preview'] or '',
            })
        cur.close()
        conn.close()
        return {"threads": threads, "total": total, "page": page, "per_page": per_page}

    def get_thread_messages(self, device_id, thread_id):
        conn = self._get_conn()
        cur = conn.cursor()
        sub_ids = self._resolve_device_ids(device_id)
        placeholders = ",".join(["%s"] * len(sub_ids))
        cur.execute(f"SELECT * FROM chat_messages WHERE device_id IN ({placeholders}) AND thread_num=%s ORDER BY timestamp",
                         sub_ids + [thread_id])
        rows = cur.fetchall()
        messages = [{"timestamp": r["timestamp"], "sender": r["sender"], "body": r["body"], "source_app": r["source_app"]} for r in rows]
        cur.close()
        conn.close()
        return {"messages": messages, "total": len(messages)}

    def _rebuild_caches(self):
        conn = self._get_conn()
        cur = conn.cursor()
        # Devices cache - build raw list first
        cur.execute("SELECT * FROM devices ORDER BY source, owner, device_id")
        rows = cur.fetchall()
        raw_devices = []
        for r in rows:
            cats = {}
            cur.execute("SELECT category, count FROM device_category_counts WHERE device_id=%s", (r["device_id"],))
            for cr in cur.fetchall():
                cats[cr["category"]] = cr["count"]
            raw_devices.append({
                "id": r["device_id"], "name": r["name"], "type": r["type"],
                "owner": r["owner"], "source": r["source"],
                "categories": cats, "total_records": sum(cats.values()),
            })

        # Merge devices sharing the same RMR number
        rmr_groups = {}  # rmr_number -> list of devices
        non_rmr = []
        for d in raw_devices:
            parsed = _extract_rmr_base(d["id"])
            if parsed:
                rmr = parsed[0]
                rmr_groups.setdefault(rmr, []).append((d, parsed))
            else:
                non_rmr.append(d)

        devices = list(non_rmr)  # keep cellebrite devices as-is
        # Also build a mapping from merged_id -> [sub_device_ids]
        self._merged_device_map = {}  # merged_id -> [original device_ids]

        for rmr, group in sorted(rmr_groups.items()):
            if len(group) == 1:
                # Single extraction, keep as-is but add extractions info
                d, (_, base_type, suffix) = group[0]
                d["extractions"] = [{"id": d["id"], "source": d["source"], "suffix": suffix or "Primary"}]
                devices.append(d)
                self._merged_device_map[d["id"]] = [d["id"]]
            else:
                # Multiple extractions - merge
                merged_cats = defaultdict(int)
                extractions = []
                owner = "Unknown"
                source = "axiom"
                base_type = ""
                sub_ids = []
                for d, (_, bt, suffix) in group:
                    for cat, cnt in d["categories"].items():
                        merged_cats[cat] += cnt
                    extractions.append({
                        "id": d["id"],
                        "source": d["source"],
                        "suffix": suffix or "Primary",
                        "total_records": d["total_records"],
                    })
                    if d["owner"] and d["owner"] != "Unknown":
                        owner = d["owner"]
                    source = d["source"]
                    if not base_type:
                        base_type = bt
                    sub_ids.append(d["id"])

                # Get AXIOM type info for friendly name
                type_info = AXIOM_DEVICE_MAP.get(group[0][0]["id"], {})
                # Strip suffix qualifiers from type
                clean_type = re.sub(r'\s*\((?:TaintClear|nonPriv|NonPriv|Non-Priv|\d+)\)\s*$', '', type_info.get("type", base_type))

                merged = {
                    "id": rmr,
                    "name": _friendly_device_name(base_type, rmr),
                    "type": clean_type,
                    "owner": owner,
                    "source": source,
                    "categories": dict(merged_cats),
                    "total_records": sum(merged_cats.values()),
                    "extractions": extractions,
                    "merged": True,
                }
                devices.append(merged)
                self._merged_device_map[rmr] = sub_ids
                # Also map each sub-id to itself for direct access
                for sid in sub_ids:
                    self._merged_device_map[sid] = [sid]

        self._devices_cache = devices

        # Stats cache
        cat_totals = defaultdict(int)
        for d in devices:
            for cat, cnt in d["categories"].items():
                if d["source"] == "axiom":
                    cat_totals["axiom_records"] += cnt
                else:
                    cat_totals[cat] += cnt
        cel = sum(1 for d in devices if d["source"] == "cellebrite")
        axm = sum(1 for d in devices if d["source"] == "axiom")
        self._stats_cache = {
            "total_devices": len(devices),
            "cellebrite_devices": cel,
            "axiom_devices": axm,
            "categories": dict(cat_totals),
            "rag_chunks": self._rag_chunk_count,
            "last_indexed": self._last_index_time,
        }
        
        cur.close()
        conn.close()

    # ─── Discoveries ───

    def _compute_discoveries(self, conn):
        from discovery_engine import scan_discoveries_from_db
        cur = conn.cursor()
        cur.execute("DELETE FROM discoveries")
        # Pass the connection object to the scanner
        discs = scan_discoveries_from_db(conn, DEVICE_MAP)
        batch = []
        for d in discs:
            batch.append((
                d["id"], d["title"], d["category"], d["flames"],
                d.get("device_id"), d.get("owner", ""),
                d.get("content", ""), d.get("timestamp"),
                1 if d.get("verified") else 0,
                json.dumps(d.get("tags", [])),
                d.get("data_type", ""), d.get("source_app", ""),
            ))
        execute_batch(cur, "INSERT INTO discoveries VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", batch)
        conn.commit()
        self._discoveries_cache = None  # invalidate
        _log.info(f'Discoveries computed: {len(batch)}')

    def get_discoveries(self, category="all", person="all", sort="importance", page=1, per_page=50):
        conn = self._get_conn()
        cur = conn.cursor()
        # Category counts (cached)
        if self._discoveries_cache is None:
            cur.execute("SELECT category, COUNT(*) as cnt FROM discoveries GROUP BY category")
            rows = cur.fetchall()
            self._discoveries_cache = {r["category"]: r["cnt"] for r in rows}

        # Build query
        where = []
        params = []
        if category != "all":
            where.append("category = %s")
            params.append(category)
        if person != "all":
            where.append("(owner LIKE %s OR tags LIKE %s)")
            params.extend([f"%{person}%", f"%{person}%"])

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        order = "flames DESC, verified DESC, timestamp DESC"
        if sort == "date":
            order = "timestamp DESC"
        elif sort == "date_asc":
            order = "timestamp ASC"

        cur.execute(f"SELECT COUNT(*) as count FROM discoveries{where_sql}", params)
        total = cur.fetchone()['count']
        offset = (page - 1) * per_page
        cur.execute(
            f"SELECT * FROM discoveries{where_sql} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [per_page, offset]
        )
        rows = cur.fetchall()

        result = {
            "discoveries": [self._disc_row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "category_counts": self._discoveries_cache,
        }
        cur.close()
        conn.close()
        return result

    def _disc_row_to_dict(self, r):
        return {
            "id": r["id"], "title": r["title"], "category": r["category"],
            "flames": r["flames"], "device_id": r["device_id"],
            "owner": r["owner"], "content": r["content"],
            "timestamp": r["timestamp"], "verified": bool(r["verified"]),
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "data_type": r["data_type"], "source_app": r["source_app"],
        }

    # ─── Query API ───

    def get_stats(self):
        if not self._stats_cache:
            self._rebuild_caches()
        return self._stats_cache

    def get_devices(self):
        if not self._devices_cache:
            self._rebuild_caches()
        return self._devices_cache

    def _resolve_device_ids(self, device_id):
        """Resolve a device_id (possibly merged) to list of actual DB device_ids."""
        if hasattr(self, '_merged_device_map') and device_id in self._merged_device_map:
            return self._merged_device_map[device_id]
        return [device_id]

    def get_device_data(self, device_id, category=None, page=1, per_page=100, query=None, date_from=None, date_to=None):
        conn = self._get_conn()
        cur = conn.cursor()
        sub_ids = self._resolve_device_ids(device_id)

        # Check first sub-device for source type
        cur.execute("SELECT source FROM devices WHERE device_id=%s", (sub_ids[0],))
        dev = cur.fetchone()
        if not dev:
            cur.close()
            conn.close()
            return {"records": [], "total": 0, "page": page, "per_page": per_page}

        if dev["source"] == "axiom":
            if len(sub_ids) > 1:
                result = self._get_axiom_data_merged(sub_ids, category, page, per_page, query)
            else:
                result = self._get_axiom_data(sub_ids[0], category, page, per_page, query)
            cur.close()
            conn.close()
            return result

        # Cellebrite — from Postgres
        placeholders = ",".join(["%s"] * len(sub_ids))
        where = [f"device_id IN ({placeholders})"]
        params = list(sub_ids)
        if category:
            where.append("category = %s")
            params.append(category)
        if date_from:
            where.append("timestamp >= %s")
            params.append(date_from)
        if date_to:
            where.append("timestamp <= %s")
            params.append(date_to + 'T23:59:59')

        if query:
            # Use simple text search (can upgrade to pg tsvector later)
            where.append("searchable ILIKE %s")
            params.append(f"%{query}%")

        where_sql = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) as count FROM records WHERE {where_sql}", params)
        total = cur.fetchone()['count']
        offset = (page - 1) * per_page
        cur.execute(
            f"SELECT data, category FROM records WHERE {where_sql} ORDER BY timestamp DESC LIMIT %s OFFSET %s",
            params + [per_page, offset]
        )
        rows = cur.fetchall()

        records = []
        for r in rows:
            rec = json.loads(r["data"])
            rec["_category"] = r["category"]
            records.append(rec)

        cur.close()
        conn.close()
        return {"records": records, "total": total, "page": page, "per_page": per_page}

    def _get_axiom_data(self, device_id, category, page, per_page, query):
        conn = self._get_conn()
        cur = conn.cursor()
        if not category:
            # Return category summary
            cur.execute("SELECT category, count FROM device_category_counts WHERE device_id=%s AND count > 0 ORDER BY category",
                             (device_id,))
            rows = cur.fetchall()
            records = [{"_category": r["category"], "record_count": r["count"]} for r in rows]
            cur.close()
            conn.close()
            return {"records": records, "total": len(records), "page": 1, "per_page": len(records)}
        # Lazy-load actual AXIOM JSON
        cur.close()
        conn.close()
        fpath = AXIOM_DIR / device_id / f"{category}.json"
        if not fpath.exists():
            return {"records": [], "total": 0, "page": page, "per_page": per_page}
        try:
            with open(fpath) as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = [data]
        except Exception:
            data = []
        if query:
            ql = query.lower()
            data = [r for r in data if ql in json.dumps(r, default=str).lower()]
        total = len(data)
        offset = (page - 1) * per_page
        return {"records": data[offset:offset+per_page], "total": total, "page": page, "per_page": per_page}

    def _get_axiom_data_merged(self, sub_ids, category, page, per_page, query):
        """Get AXIOM data from multiple sub-devices (merged)."""
        conn = self._get_conn()
        cur = conn.cursor()
        if not category:
            # Return combined category summary
            cat_totals = defaultdict(int)
            for sid in sub_ids:
                cur.execute("SELECT category, count FROM device_category_counts WHERE device_id=%s AND count > 0", (sid,))
                rows = cur.fetchall()
                for r in rows:
                    cat_totals[r["category"]] += r["count"]
            records = [{"_category": k, "record_count": v} for k, v in sorted(cat_totals.items())]
            cur.close()
            conn.close()
            return {"records": records, "total": len(records), "page": 1, "per_page": len(records)}

        # Merge JSON data from all sub-devices
        cur.close()
        conn.close()
        all_data = []
        for sid in sub_ids:
            fpath = AXIOM_DIR / sid / f"{category}.json"
            if not fpath.exists():
                continue
            try:
                with open(fpath) as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                # Tag each record with source extraction
                for rec in data:
                    rec["_extraction"] = sid
                all_data.extend(data)
            except Exception:
                pass
        if query:
            ql = query.lower()
            all_data = [r for r in all_data if ql in json.dumps(r, default=str).lower()]
        total = len(all_data)
        offset = (page - 1) * per_page
        return {"records": all_data[offset:offset+per_page], "total": total, "page": page, "per_page": per_page}

    def search_all(self, query, device_filter=None, category_filter=None, page=1, per_page=50):
        """Text search across all records."""
        conn = self._get_conn()
        cur = conn.cursor()
        where = ["searchable ILIKE %s"]
        params = [f"%{query}%"]

        if device_filter:
            where.append("r.device_id = %s")
            params.append(device_filter)
        if category_filter:
            where.append("r.category = %s")
            params.append(category_filter)

        where_sql = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) as count FROM records r WHERE {where_sql}", params)
        total = cur.fetchone()['count']
        offset = (page - 1) * per_page
        cur.execute(f"""
            SELECT r.data, r.category, r.device_id, d.name as device_name, d.owner
            FROM records r JOIN devices d ON r.device_id = d.device_id
            WHERE {where_sql}
            ORDER BY r.timestamp DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "device_id": r["device_id"], "device_name": r["device_name"],
                "owner": r["owner"], "category": r["category"],
                "source": "cellebrite", "record": json.loads(r["data"]),
            })
        cur.close()
        conn.close()
        return {"results": results, "total": total, "page": page, "per_page": per_page}

    # ─── Refresh / File Watching ───

    def refresh(self):
        """Re-index changed files."""
        with self._lock:
            t0 = time.time()
            conn = self._get_conn()
            cur = conn.cursor()
            changed = self._detect_changes(conn)
            if not changed:
                cur.close()
                conn.close()
                return {"changed": 0, "time": 0}

            # Re-index changed cellebrite files
            for fpath_str in changed:
                fpath = Path(fpath_str)
                if not fpath.exists():
                    continue
                parts = fpath.stem.split('_', 1)
                if len(parts) != 2:
                    continue
                person_id, cat = parts
                if person_id not in DEVICE_MAP:
                    continue
                # Delete old records
                cur.execute("DELETE FROM records WHERE device_id=%s AND category=%s", (person_id, cat))
                # Re-parse
                parser = PARSERS.get(cat, _parse_generic)
                count = 0
                batch = []
                for rec in parser(fpath):
                    data_json = json.dumps(rec, ensure_ascii=False)
                    searchable = " ".join(str(v) for v in rec.values() if v)
                    ts = rec.get("timestamp", "")
                    batch.append((person_id, cat, ts, data_json, searchable))
                    count += 1
                if batch:
                    execute_batch(cur, "INSERT INTO records (device_id,category,timestamp,data,searchable) VALUES (%s,%s,%s,%s,%s)", batch)
                cur.execute("INSERT INTO device_category_counts VALUES (%s,%s,%s) ON CONFLICT (device_id,category) DO UPDATE SET count=EXCLUDED.count",
                           (person_id, cat, count))
                cur.execute("INSERT INTO file_index VALUES (%s,%s,%s) ON CONFLICT (file_path) DO UPDATE SET mtime=EXCLUDED.mtime, record_count=EXCLUDED.record_count",
                           (str(fpath), fpath.stat().st_mtime, count))

            conn.commit()

            # Recompute discoveries
            self._compute_discoveries(conn)
            self._rebuild_caches()
            self._last_index_time = time.time()
            self._rag_chunk_count = self._get_rag_count()

            dt = time.time() - t0
            cur.close()
            conn.close()
            return {"changed": len(changed), "time": round(dt, 1)}

    def _detect_changes(self, conn):
        cur = conn.cursor()
        changed = []
        for person_id in DEVICE_MAP:
            for cat in CATEGORIES:
                fpath = CELLEBRITE_DIR / f"{person_id}_{cat}.md"
                if not fpath.exists():
                    continue
                current_mtime = fpath.stat().st_mtime
                cur.execute("SELECT mtime FROM file_index WHERE file_path=%s", (str(fpath),))
                row = cur.fetchone()
                if not row or row["mtime"] != current_mtime:
                    changed.append(str(fpath))
        return changed

    def _get_rag_count(self):
        """Get RAG chunk count from Postgres."""
        try:
            conn = psycopg2.connect(POSTGRES_CONN)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM documents")
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return count
        except Exception:
            return 0

    def start_watcher(self, interval=30):
        """Start background file watcher thread."""
        def _watch():
            while True:
                time.sleep(interval)
                try:
                    result = self.refresh()
                    if result["changed"]:
                        _log.info(f'Watcher re-indexed {result["changed"]} files in {result["time"]}s')
                except Exception as e:
                    _log.error(f'Watcher error: {e}')
        self._watcher_thread = threading.Thread(target=_watch, daemon=True)
        self._watcher_thread.start()
        _log.info(f'File watcher started (interval={interval}s)')


# Singleton
db = EvidenceDB()

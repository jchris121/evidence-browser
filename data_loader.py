"""Parse Cellebrite markdown files and AXIOM JSON into structured data.
Uses line-by-line parsing (not regex) for performance on large files.
AXIOM data is loaded lazily (on demand) due to 2GB+ total size."""
import os
import re
import json
from pathlib import Path
from collections import defaultdict

CELLEBRITE_DIR = Path.home() / "clawd/tina-legal/cellebrite-parsed"
AXIOM_DIR = Path.home() / "clawd/rag/inbox/axiom-extracts"

DEVICE_MAP = {
    "belinda-knisley": {"id": "belinda-knisley", "name": "Belinda Knisley Phone", "type": "Phone", "owner": "Belinda Knisley", "source": "cellebrite"},
    "joy-quinn": {"id": "joy-quinn", "name": "Joy Quinn iPhone", "type": "iPhone", "owner": "Joy Quinn", "source": "cellebrite"},
    "wendi-woods": {"id": "wendi-woods", "name": "Wendi Woods iPhone", "type": "iPhone", "owner": "Wendi Woods", "source": "cellebrite"},
    "zachary-quinn": {"id": "zachary-quinn", "name": "Zachary Quinn Phone", "type": "Phone", "owner": "Zachary Quinn", "source": "cellebrite"},
}

AXIOM_DEVICE_MAP = {
    "RMR034359_White iPhone SE": {"owner": "Tina Peters", "type": "White iPhone SE"},
    "RMR034359_White iPhone SE_TaintClear": {"owner": "Tina Peters", "type": "White iPhone SE (TaintClear)"},
    "RMR034364_BlackiPhoneSE_TaintClear": {"owner": "Unknown", "type": "Black iPhone SE (TaintClear)"},
    "RMR034365_1stiPhone7_nonPriv": {"owner": "Tina Peters", "type": "iPhone 7"},
    "RMR034366_2ndiPhone7_nonPriv": {"owner": "Unknown", "type": "2nd iPhone 7"},
    "RMR034367_CompaqLaptop_TaintClear": {"owner": "Tina Peters", "type": "Compaq Laptop"},
    "RMR034371_Samsung_nonPriv": {"owner": "Sandra Brown", "type": "Samsung"},
    "RMR034371_Samsung_TaintClear": {"owner": "Sandra Brown", "type": "Samsung (TaintClear)"},
    "RMR034372 Motorola": {"owner": "Sandra Brown", "type": "Motorola"},
    "RMR034372_Motorola_TaintClear": {"owner": "Sandra Brown", "type": "Motorola (TaintClear)"},
    "RMR034373_LGTablet_NonPriv": {"owner": "Unknown", "type": "LG Tablet"},
    "RMR034374_HPLaptop_NonPriv": {"owner": "Unknown", "type": "HP Laptop (374)"},
    "RMR034375_ASUSLaptop_Non-Priv": {"owner": "Unknown", "type": "ASUS Laptop (375)"},
    "RMR034376_HPDesktop": {"owner": "Unknown", "type": "HP Desktop"},
    "RMR034376_HPDesktop_nonPriv": {"owner": "Unknown", "type": "HP Desktop (nonPriv)"},
    "RMR034378_iPhone_nonPriv": {"owner": "Gerald Wood", "type": "iPhone"},
    "RMR034378_iPhoneTaintClear": {"owner": "Gerald Wood", "type": "iPhone (TaintClear)"},
    "RMR034379_BluPhone_nonPriv": {"owner": "Unknown", "type": "Blu Phone"},
    "RMR034381_ASUSLaptop_nonPriv": {"owner": "Unknown", "type": "ASUS Laptop (381)"},
    "RMR034382_MSILaptop_nonPriv": {"owner": "Unknown", "type": "MSI Laptop"},
    "RMR034704_HPLaptop": {"owner": "Sherronna Bishop", "type": "HP Laptop"},
    "RMR034704_HPLaptop_nonPriv": {"owner": "Sherronna Bishop", "type": "HP Laptop (nonPriv)"},
    "RMR034705_LenovoAllinOne_nonPriv": {"owner": "Unknown", "type": "Lenovo All-in-One"},
    "RMR035374_HPLaptop_TaintClear": {"owner": "Unknown", "type": "HP Laptop (TaintClear)"},
    "RMR035375_ASUSLaptop_TaintClear": {"owner": "Unknown", "type": "ASUS Laptop (TaintClear)"},
}

CATEGORIES = ["browsing", "calls", "chats", "contacts", "emails", "locations", "notes", "passwords", "searches", "voicemails"]

# Line-by-line parsers (fast)
def parse_chats(fpath):
    """Parse chat messages line by line."""
    messages = []
    pat = re.compile(r'^- \[(\d{4}-\d{2}-\d{2}T[^\]]+)\] \*\*([^*]*)\*\*: (.+)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                ts, sender, body = m.group(1), m.group(2), m.group(3).strip()
                # Extract source in trailing parens
                idx = body.rfind('(')
                if idx > 0 and body.endswith(')'):
                    source = body[idx+1:-1]
                    body = body[:idx].strip()
                else:
                    source = ""
                messages.append({"timestamp": ts, "sender": sender, "body": body, "source": source})
    return messages


def parse_chat_threads(fpath):
    """Parse chat file into thread structures with metadata."""
    threads = []
    current_thread = None
    thread_id = 0
    msg_pat = re.compile(r'^- \[(\d{4}-\d{2}-\d{2}T[^\]]+)\] \*\*([^*]*)\*\*: (.+)')
    header_pat = re.compile(r'^### Chat: (.+)')
    started_pat = re.compile(r'^\*\*Started:\*\* (.+)')

    with open(fpath, errors='replace') as f:
        for line in f:
            hm = header_pat.match(line)
            if hm:
                if current_thread and current_thread['messages']:
                    threads.append(current_thread)
                thread_id += 1
                current_thread = {
                    'thread_id': thread_id,
                    'source': hm.group(1).strip(),
                    'started': '',
                    'messages': [],
                    'participants': set(),
                }
                continue

            if current_thread is not None:
                sm = started_pat.match(line)
                if sm:
                    current_thread['started'] = sm.group(1).strip()
                    continue

            mm = msg_pat.match(line)
            if mm:
                ts, sender, body = mm.group(1), mm.group(2), mm.group(3).strip()
                idx = body.rfind('(')
                if idx > 0 and body.endswith(')'):
                    source = body[idx+1:-1]
                    body = body[:idx].strip()
                else:
                    source = ""
                if current_thread is None:
                    thread_id += 1
                    current_thread = {
                        'thread_id': thread_id,
                        'source': source or 'Unknown',
                        'started': ts,
                        'messages': [],
                        'participants': set(),
                    }
                current_thread['messages'].append({
                    'timestamp': ts, 'sender': sender, 'body': body, 'source': source
                })
                if sender:
                    current_thread['participants'].add(sender)

    if current_thread and current_thread['messages']:
        threads.append(current_thread)

    # Build summary for each thread
    result = []
    for t in threads:
        msgs = t['messages']
        participants = list(t['participants']) if t['participants'] else ['Unknown']
        first_date = msgs[0]['timestamp'] if msgs else t.get('started', '')
        last_date = msgs[-1]['timestamp'] if msgs else first_date
        last_msg = msgs[-1]['body'][:150] if msgs else ''
        result.append({
            'thread_id': t['thread_id'],
            'source': t['source'],
            'participants': participants,
            'message_count': len(msgs),
            'first_date': first_date,
            'last_date': last_date,
            'last_message_preview': last_msg,
        })
    return result, {t['thread_id']: t['messages'] for t in threads}

def parse_calls(fpath):
    calls = []
    pat = re.compile(r'^- \*\*(\d{4}-\d{2}-\d{2}T[^*]+)\*\* \| (\w+) \| (\w+) \| Duration: ([^ |]+)(.*)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                calls.append({"timestamp": m.group(1), "direction": m.group(2), "status": m.group(3), "duration": m.group(4), "details": m.group(5).strip(' |')})
    return calls

def parse_contacts(fpath):
    contacts = []
    pat = re.compile(r'^- \*\*([^*]+)\*\* \| Source: (.+)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                contacts.append({"name": m.group(1), "source": m.group(2).strip()})
    return contacts

def parse_browsing(fpath):
    entries = []
    pat = re.compile(r'^- \*\*(\d{4}-\d{2}-\d{2}T[^*]+)\*\* \| \[([^\]]*)\]\(([^)]*)\) \| (.+)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                entries.append({"timestamp": m.group(1), "title": m.group(2), "url": m.group(3), "browser": m.group(4).strip()})
    return entries

def parse_searches(fpath):
    entries = []
    pat = re.compile(r'^- \*\*([^*]*)\*\* \| (.+?) \| (.+)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                entries.append({"timestamp": m.group(1), "query": m.group(2), "source": m.group(3).strip()})
    return entries

def parse_emails(fpath):
    """Parse emails - multiline, need to track state."""
    emails = []
    with open(fpath, errors='replace') as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('### ') and '—' in line:
            # Parse: ### 2021-08-23T22:08:17+00:00 — Subject
            parts = line[4:].split('—', 1)
            ts = parts[0].strip()
            subject = parts[1].strip() if len(parts) > 1 else ""
            # Next line: **From:** ... → **To:** ...
            i += 1
            from_to = ""
            source = ""
            if i < len(lines):
                ft_line = lines[i]
                ft_match = re.match(r'\*\*From:\*\*\s*(.*?)\s*→\s*\*\*To:\*\*\s*(.*)', ft_line)
                if ft_match:
                    from_addr = ft_match.group(1).strip()
                    to_addr = ft_match.group(2).strip()
                else:
                    from_addr = to_addr = ""
                i += 1
                if i < len(lines) and lines[i].startswith('**Source:**'):
                    source = lines[i].replace('**Source:**', '').strip()
                    i += 1
            # Grab preview (skip HTML, get text)
            preview = ""
            while i < len(lines) and not lines[i].startswith('---') and not lines[i].startswith('### '):
                clean = re.sub(r'<[^>]+>', '', lines[i]).strip()
                if clean and len(preview) < 300:
                    preview += clean + " "
                i += 1
            emails.append({"timestamp": ts, "subject": subject, "from": from_addr, "to": to_addr, "source": source, "preview": preview[:300].strip()})
        else:
            i += 1
    return emails

def parse_locations(fpath):
    entries = []
    pat = re.compile(r'^- \*\*([^*]*)\*\* \| ([^|]*)\|(.+)')
    with open(fpath, errors='replace') as f:
        for line in f:
            m = pat.match(line)
            if m:
                rest = m.group(3).strip()
                parts = rest.split('|')
                if len(parts) >= 2:
                    entries.append({"timestamp": m.group(1), "coords": m.group(2).strip(), "address": parts[0].strip(), "source": parts[1].strip()})
                else:
                    entries.append({"timestamp": m.group(1), "coords": m.group(2).strip(), "address": "", "source": rest})
    return entries

def parse_generic(fpath):
    entries = []
    with open(fpath, errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('- '):
                entries.append({"content": line[2:][:500]})
    return entries

PARSERS = {
    "chats": parse_chats, "calls": parse_calls, "contacts": parse_contacts,
    "browsing": parse_browsing, "searches": parse_searches, "emails": parse_emails,
    "locations": parse_locations, "notes": parse_generic, "passwords": parse_generic, "voicemails": parse_generic,
}


class DataStore:
    def __init__(self):
        self.cellebrite_data = {}
        self.chat_threads = {}      # device_id -> list of thread summaries
        self.chat_thread_msgs = {}  # device_id -> {thread_id -> [messages]}
        self.axiom_index = {}
        self.devices = []
        self.stats = {}

    def load_all(self):
        print("Loading Cellebrite data...")
        self._load_cellebrite()
        print("Indexing AXIOM data...")
        self._index_axiom()
        self._compute_stats()
        print(f"Loaded {len(self.devices)} devices")

    def _load_cellebrite(self):
        for person_id in DEVICE_MAP:
            self.cellebrite_data[person_id] = {}
            for cat in CATEGORIES:
                fpath = CELLEBRITE_DIR / f"{person_id}_{cat}.md"
                if fpath.exists():
                    parser = PARSERS.get(cat, parse_generic)
                    try:
                        records = parser(fpath)
                    except Exception as e:
                        print(f"  Error parsing {fpath.name}: {e}")
                        records = []
                    self.cellebrite_data[person_id][cat] = records
                    print(f"  {person_id}/{cat}: {len(records)} records")
                    # Also parse chat threads
                    if cat == 'chats':
                        try:
                            thread_summaries, thread_messages = parse_chat_threads(fpath)
                            self.chat_threads[person_id] = thread_summaries
                            self.chat_thread_msgs[person_id] = thread_messages
                            print(f"  {person_id}/chat-threads: {len(thread_summaries)} threads")
                        except Exception as e:
                            print(f"  Error parsing threads for {fpath.name}: {e}")

    def _index_axiom(self):
        if not AXIOM_DIR.exists():
            return
        for dirname in sorted(os.listdir(AXIOM_DIR)):
            dirpath = AXIOM_DIR / dirname
            if not dirpath.is_dir():
                continue
            file_index = {}
            for jf in sorted(dirpath.glob("*.json")):
                fsize = jf.stat().st_size
                file_index[jf.stem] = max(1, fsize // 500)
            self.axiom_index[dirname] = file_index

    def _load_axiom_file(self, device_id, category):
        fpath = AXIOM_DIR / device_id / f"{category}.json"
        if not fpath.exists():
            return []
        try:
            with open(fpath) as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]
        except Exception:
            return []

    def _compute_stats(self):
        self.devices = []
        total_stats = defaultdict(int)

        for person_id, device_info in DEVICE_MAP.items():
            cats = self.cellebrite_data.get(person_id, {})
            dev = {**device_info, "categories": {}}
            for cat, records in cats.items():
                dev["categories"][cat] = len(records)
                total_stats[cat] += len(records)
            dev["total_records"] = sum(dev["categories"].values())
            self.devices.append(dev)

        for dirname, file_index in self.axiom_index.items():
            info = AXIOM_DEVICE_MAP.get(dirname, {"owner": "Unknown", "type": dirname})
            dev = {
                "id": dirname, "name": dirname, "type": info["type"],
                "owner": info["owner"], "source": "axiom",
                "categories": file_index,
                "total_records": sum(file_index.values()),
            }
            total_stats["axiom_records"] += dev["total_records"]
            self.devices.append(dev)

        self.stats = {
            "total_devices": len(self.devices),
            "cellebrite_devices": len(DEVICE_MAP),
            "axiom_devices": len(self.axiom_index),
            "categories": dict(total_stats),
        }

    def get_chat_threads(self, device_id, page=1, per_page=50, search=None, date_from=None, date_to=None):
        threads = self.chat_threads.get(device_id, [])
        if date_from:
            threads = [t for t in threads if (t.get('last_date') or '') >= date_from]
        if date_to:
            threads = [t for t in threads if (t.get('first_date') or '') <= date_to + 'T23:59:59']
        if search:
            sl = search.lower()
            threads = [t for t in threads if sl in str(t.get('participants', [])).lower() or sl in t.get('last_message_preview', '').lower() or sl in t.get('source', '').lower()]
        total = len(threads)
        start = (page - 1) * per_page
        return {"threads": threads[start:start+per_page], "total": total, "page": page, "per_page": per_page}

    def get_thread_messages(self, device_id, thread_id):
        msgs = self.chat_thread_msgs.get(device_id, {}).get(thread_id, [])
        return {"messages": msgs, "total": len(msgs)}

    def get_device_data(self, device_id, category=None, page=1, per_page=100, query=None, date_from=None, date_to=None):
        if device_id in self.cellebrite_data:
            data = self.cellebrite_data[device_id]
            if category:
                records = data.get(category, [])
            else:
                records = []
                for cat, recs in data.items():
                    for r in recs:
                        records.append({**r, "_category": cat})
            # Date filtering
            if date_from:
                records = [r for r in records if (r.get('timestamp') or '') >= date_from]
            if date_to:
                records = [r for r in records if (r.get('timestamp') or '') <= date_to + 'T23:59:59']
            if query:
                ql = query.lower()
                records = [r for r in records if ql in str(r).lower()]
            total = len(records)
            start = (page - 1) * per_page
            return {"records": records[start:start+per_page], "total": total, "page": page, "per_page": per_page}

        if device_id in self.axiom_index:
            if category:
                records = self._load_axiom_file(device_id, category)
                if query:
                    ql = query.lower()
                    records = [r for r in records if ql in json.dumps(r, default=str).lower()]
                total = len(records)
                start = (page - 1) * per_page
                return {"records": records[start:start+per_page], "total": total, "page": page, "per_page": per_page}
            else:
                records = [{"_category": k, "record_count": v} for k, v in sorted(self.axiom_index[device_id].items()) if v > 0]
                total = len(records)
                start = (page - 1) * per_page
                return {"records": records[start:start+per_page], "total": total, "page": page, "per_page": per_page}

        return {"records": [], "total": 0, "page": page, "per_page": per_page}

    def search_all(self, query, device_filter=None, category_filter=None, page=1, per_page=50):
        results = []
        ql = query.lower()

        for device_id, cats in self.cellebrite_data.items():
            if device_filter and device_id != device_filter:
                continue
            device_info = DEVICE_MAP.get(device_id, {})
            for cat, records in cats.items():
                if category_filter and cat != category_filter:
                    continue
                for r in records:
                    if ql in str(r).lower():
                        results.append({
                            "device_id": device_id, "device_name": device_info.get("name", device_id),
                            "owner": device_info.get("owner", "Unknown"), "category": cat,
                            "source": "cellebrite", "record": r
                        })
                        if len(results) >= 500:
                            break

        total = len(results)
        start = (page - 1) * per_page
        return {"results": results[start:start+per_page], "total": total, "page": page, "per_page": per_page}


    def scan_discoveries(self):
        """Scan parsed data for notable/interesting items."""
        discoveries = []
        disc_id = 0
        keywords_3 = ["trusted build", "delete signal", "erase", "password", "backup image", "gold hill"]
        keywords_2 = ["dominion", "griswold", "ballot", "adjudication", "mcua", "conan", "hayes", "backup"]
        keywords_1 = ["delete", "password", "image"]

        def flames_for(text):
            tl = text.lower()
            for kw in keywords_3:
                if kw in tl:
                    return 3
            for kw in keywords_2:
                if kw in tl:
                    return 2
            return 1

        def person_label(device_id):
            info = DEVICE_MAP.get(device_id, {})
            return info.get("owner", device_id)

        all_keywords = keywords_3 + keywords_2 + ["delete", "image", "dominion", "ballot", "password"]

        for device_id, cats in self.cellebrite_data.items():
            owner = person_label(device_id)

            # Scan chats
            for msg in cats.get("chats", []):
                body = (msg.get("body") or "").lower()
                for kw in all_keywords:
                    if kw in body:
                        disc_id += 1
                        discoveries.append({
                            "id": f"disc-{disc_id:04d}",
                            "flames": flames_for(msg.get("body", "")),
                            "title": f"{owner}: \"{msg.get('body', '')[:80]}\"",
                            "category": "chats",
                            "person": device_id,
                            "person_name": owner,
                            "content": msg.get("body", ""),
                            "timestamp": msg.get("timestamp", ""),
                            "source_file": f"{device_id}_chats.md",
                            "sender": msg.get("sender", ""),
                        })
                        break

            # Scan searches
            for s in cats.get("searches", []):
                query = (s.get("query") or "").lower()
                for kw in all_keywords:
                    if kw in query:
                        disc_id += 1
                        discoveries.append({
                            "id": f"disc-{disc_id:04d}",
                            "flames": flames_for(s.get("query", "")),
                            "title": f"{owner} searched: \"{s.get('query', '')[:80]}\"",
                            "category": "searches",
                            "person": device_id,
                            "person_name": owner,
                            "content": s.get("query", ""),
                            "timestamp": s.get("timestamp", ""),
                            "source_file": f"{device_id}_searches.md",
                        })
                        break

            # Scan passwords
            for p in cats.get("passwords", []):
                disc_id += 1
                content = p.get("content", "")
                discoveries.append({
                    "id": f"disc-{disc_id:04d}",
                    "flames": 2,
                    "title": f"{owner} stored password: {content[:60]}",
                    "category": "passwords",
                    "person": device_id,
                    "person_name": owner,
                    "content": content,
                    "timestamp": "",
                    "source_file": f"{device_id}_passwords.md",
                })

            # Scan emails
            for e in cats.get("emails", []):
                text = f"{e.get('subject', '')} {e.get('preview', '')}".lower()
                for kw in all_keywords:
                    if kw in text:
                        disc_id += 1
                        discoveries.append({
                            "id": f"disc-{disc_id:04d}",
                            "flames": flames_for(f"{e.get('subject', '')} {e.get('preview', '')}"),
                            "title": f"{owner} email: \"{e.get('subject', '')[:80]}\"",
                            "category": "emails",
                            "person": device_id,
                            "person_name": owner,
                            "content": f"Subject: {e.get('subject', '')}\nFrom: {e.get('from', '')}\nTo: {e.get('to', '')}\n{e.get('preview', '')}",
                            "timestamp": e.get("timestamp", ""),
                            "source_file": f"{device_id}_emails.md",
                        })
                        break

        # Sort by flames desc, then timestamp
        discoveries.sort(key=lambda d: (-d["flames"], d.get("timestamp", "") or ""), reverse=False)
        discoveries.sort(key=lambda d: -d["flames"])
        self._discoveries = discoveries
        print(f"  Found {len(discoveries)} discoveries")
        return discoveries

    def get_discoveries(self, category=None, person=None, min_flames=None):
        discs = getattr(self, '_discoveries', [])
        if category and category != 'all':
            discs = [d for d in discs if d['category'] == category]
        if person and person != 'all':
            discs = [d for d in discs if d['person'] == person]
        if min_flames:
            discs = [d for d in discs if d['flames'] >= int(min_flames)]
        return discs


store = DataStore()

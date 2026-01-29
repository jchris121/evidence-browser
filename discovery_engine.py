"""Discovery engine — scans parsed evidence for notable/groundbreaking findings.
Works from PostgreSQL records table for speed."""
import re
import json
from collections import defaultdict

# Key terms and their importance (flames 1-3)
KEY_TERMS = {
    # 3 flames — critical case terms
    "trusted build": 3, "Gold Hill": 3, "adjudication": 3,
    "Conan": 3, "Hayes": 3, "Griswold": 3, "ballot image": 3,
    # 2 flames — important operational terms
    "Dominion": 2, "MCUA": 2, "M.C.U.A": 2,
    "forensic image": 2, "election fraud": 2,
    "voting system": 2, "Secretary of State": 2,
    "Dominion Voting": 2, "election security": 2,
    # 1 flame — interesting context
    "ballot": 1, "audit": 1, "tabulator": 1,
    "Mike Lindell": 1, "MyPillow": 1, "cyber symposium": 1,
    "Jessi Romero": 1, "Judd Choate": 1,
}

# Critical dates
CRITICAL_DATES = {
    "2021-05-23": ("Trusted Build Weekend", 3),
    "2021-05-24": ("Trusted Build Weekend", 3),
    "2021-05-25": ("Trusted Build Day", 3),
    "2021-05-26": ("Post Trusted Build", 3),
    "2021-08-10": ("Second Scan / SOS Investigation Announced", 3),
    "2021-08-11": ("Second Scan Day", 3),
    "2021-08-09": ("SOS Investigation Announced", 3),
    "2021-08-12": ("Post Second Scan", 2),
    "2021-07-29": ("Mesa County Forensic Image Timing", 2),
    "2021-07-30": ("Mesa County Forensic Image Timing", 2),
}

# Key people for cross-device connections
KEY_PEOPLE = ["Tina Peters", "Tina", "Wendi", "Woods", "Gerald Wood", "Sherronna", "Bishop",
              "Sandra Brown", "Sandye", "Belinda", "Knisley", "Joy Quinn", "Zachary"]

# Pre-seeded verified discoveries
VERIFIED_DISCOVERIES = [
    {
        "id": "verified-1",
        "title": "DHS Confirmed Posting 'Does Not Heighten Risk' — Defense Gold",
        "category": "Cross-Device",
        "flames": 3,
        "device_id": None,
        "owner": "Multiple",
        "content": "DHS confirmed that the posting of Mesa County election data 'does not heighten risk' to election security. This is a critical defense finding that undermines the prosecution's claims about the severity of the alleged breach.",
        "timestamp": None,
        "verified": True,
        "tags": ["defense", "DHS", "risk assessment"],
    },
    {
        "id": "verified-2",
        "title": "Signal Group 'M.C.U.A' — Tina, Wendi Woods & Others",
        "category": "Communications",
        "flames": 3,
        "device_id": "wendi-woods",
        "owner": "Wendi Woods",
        "content": "Signal messaging group named 'MCUA' included Tina Peters, Wendi Woods, and other associates. The group was used for secure communications. A friend added Wendi to the MCUA Signal group. References found in Wendi Woods' Facebook Messenger conversations discussing the group.",
        "timestamp": "2021-08-06T21:07:24+00:00",
        "verified": True,
        "tags": ["Signal", "MCUA", "encrypted"],
    },
    {
        "id": "verified-3",
        "title": "80 Dominion Mentions in Tina's Emails, 29 Trusted Build Mentions",
        "category": "Communications",
        "flames": 2,
        "device_id": None,
        "owner": "Tina Peters",
        "content": "Tina Peters' email correspondence contains approximately 80 references to Dominion Voting Systems and 29 references to the trusted build process, indicating extensive documentation and communication about the election system and its management.",
        "timestamp": None,
        "verified": True,
        "tags": ["Dominion", "trusted build", "email"],
    },
    {
        "id": "verified-4",
        "title": "43 Dominion Mentions in Belinda Knisley's Emails",
        "category": "Communications",
        "flames": 2,
        "device_id": "belinda-knisley",
        "owner": "Belinda Knisley",
        "content": "Belinda Knisley's email correspondence contains 43 references to Dominion Voting Systems, showing her involvement in election system communications as a Mesa County Clerk & Recorder staff member.",
        "timestamp": None,
        "verified": True,
        "tags": ["Dominion", "email", "Belinda Knisley"],
    },
    {
        "id": "verified-5",
        "title": "Tina Peters iPhone FBI GrayKey Extraction — Signal, Telegram, iMessages",
        "category": "Cross-Device",
        "flames": 3,
        "device_id": None,
        "owner": "Tina Peters",
        "content": "The FBI extracted data from Tina Peters' iPhone 11 using GrayKey forensic tool. The extraction captured Signal messages, Telegram conversations, and iMessages from the June-August 2021 critical period. This is the most direct evidence of Tina's personal communications.",
        "timestamp": None,
        "verified": True,
        "tags": ["FBI", "GrayKey", "Signal", "Telegram"],
    },
    {
        "id": "verified-6",
        "title": "Joy Quinn Phone — Date Filter March 1 to August 11, 2021",
        "category": "Cross-Device",
        "flames": 2,
        "device_id": "joy-quinn",
        "owner": "Joy Quinn",
        "content": "Joy Quinn's phone data was specifically filtered for the March 1 to August 11, 2021 timeframe, covering the entire period from pre-trusted-build planning through the second scan event and SOS investigation announcement.",
        "timestamp": None,
        "verified": True,
        "tags": ["Joy Quinn", "date filter", "critical period"],
    },
]


def scan_discoveries(cellebrite_data, device_map):
    """Scan all parsed data for notable discoveries. Returns list of discovery dicts."""
    discoveries = list(VERIFIED_DISCOVERIES)  # Start with verified
    disc_id = 100

    for device_id, categories in cellebrite_data.items():
        dev_info = device_map.get(device_id, {})
        owner = dev_info.get("owner", device_id)

        # --- CHATS: Key term mentions ---
        chats = categories.get("chats", [])
        for msg in chats:
            body = msg.get("body", "")
            ts = msg.get("timestamp", "")
            if not body or len(body) < 5:
                continue

            # Check key terms (body text only, not source metadata)
            matched_terms = []
            max_flames = 0
            body_lower = body.lower()
            for term, flames in KEY_TERMS.items():
                tl = term.lower()
                if tl in body_lower:
                    # Skip common app names that appear as attribution
                    if tl in ("signal", "telegram") and len(body) < 30:
                        continue
                    matched_terms.append(term)
                    max_flames = max(max_flames, flames)

            if matched_terms and max_flames >= 2:
                disc_id += 1
                discoveries.append({
                    "id": f"chat-{device_id}-{disc_id}",
                    "title": f"{owner}: Message mentioning {', '.join(matched_terms[:3])}",
                    "category": "Communications",
                    "flames": max_flames,
                    "device_id": device_id,
                    "owner": owner,
                    "content": body[:500],
                    "timestamp": ts,
                    "verified": False,
                    "tags": matched_terms[:5],
                    "data_type": "chats",
                    "source_app": msg.get("source", ""),
                })

            # Check critical dates
            for date_str, (label, flames) in CRITICAL_DATES.items():
                if ts and ts.startswith(date_str):
                    disc_id += 1
                    discoveries.append({
                        "id": f"date-{device_id}-{disc_id}",
                        "title": f"{owner}: Message on {label} ({date_str})",
                        "category": "Communications",
                        "flames": flames,
                        "device_id": device_id,
                        "owner": owner,
                        "content": body[:500],
                        "timestamp": ts,
                        "verified": False,
                        "tags": [label, date_str],
                        "data_type": "chats",
                        "source_app": msg.get("source", ""),
                    })

        # --- EMAILS: Key term mentions ---
        emails = categories.get("emails", [])
        for email in emails:
            subject = email.get("subject", "")
            preview = email.get("preview", "")
            ts = email.get("timestamp", "")
            text = f"{subject} {preview}".lower()

            matched_terms = []
            max_flames = 0
            for term, flames in KEY_TERMS.items():
                if term.lower() in text:
                    matched_terms.append(term)
                    max_flames = max(max_flames, flames)

            if matched_terms and max_flames >= 2:
                disc_id += 1
                discoveries.append({
                    "id": f"email-{device_id}-{disc_id}",
                    "title": f"{owner}: Email — {subject[:80]}",
                    "category": "Communications",
                    "flames": max_flames,
                    "device_id": device_id,
                    "owner": owner,
                    "content": f"Subject: {subject}\n{preview[:400]}",
                    "timestamp": ts,
                    "verified": False,
                    "tags": matched_terms[:5],
                    "data_type": "emails",
                })

        # --- SEARCHES: Suspicious queries ---
        searches = categories.get("searches", [])
        for s in searches:
            query = s.get("query", "")
            ts = s.get("timestamp", "")
            q_lower = query.lower()

            matched = []
            max_flames = 0
            for term, flames in KEY_TERMS.items():
                if term.lower() in q_lower:
                    matched.append(term)
                    max_flames = max(max_flames, flames)

            # Also flag delete/erase related searches (word boundary)
            for suspicious in ["how to delete", "clear history", "delete messages", "factory reset"]:
                if suspicious in q_lower:
                    matched.append(suspicious)
                    max_flames = max(max_flames, 3)
            # Word-boundary matches for short terms
            for suspicious in ["wipe", "erase", "remove evidence"]:
                if re.search(r'\b' + re.escape(suspicious) + r'\b', q_lower):
                    matched.append(suspicious)
                    max_flames = max(max_flames, 3)

            if matched:
                disc_id += 1
                discoveries.append({
                    "id": f"search-{device_id}-{disc_id}",
                    "title": f"{owner}: Searched '{query[:60]}'",
                    "category": "Searches",
                    "flames": max_flames,
                    "device_id": device_id,
                    "owner": owner,
                    "content": f"Search query: {query}\nSource: {s.get('source', '')}\nTime: {ts}",
                    "timestamp": ts,
                    "verified": False,
                    "tags": matched[:5],
                    "data_type": "searches",
                })

        # --- PASSWORDS: All stored passwords are interesting ---
        passwords = categories.get("passwords", [])
        if passwords:
            disc_id += 1
            sample = [p.get("content", p.get("service", ""))[:80] for p in passwords[:10]]
            discoveries.append({
                "id": f"passwords-{device_id}-{disc_id}",
                "title": f"{owner}: {len(passwords)} Stored Passwords Found",
                "category": "Passwords",
                "flames": 2,
                "device_id": device_id,
                "owner": owner,
                "content": f"Found {len(passwords)} stored passwords/credentials.\nSamples:\n" + "\n".join(f"  • {s}" for s in sample),
                "timestamp": None,
                "verified": False,
                "tags": ["passwords", "credentials"],
                "data_type": "passwords",
            })

        # --- LOCATIONS: Critical dates ---
        locations = categories.get("locations", [])
        for loc in locations:
            ts = loc.get("timestamp", "")
            address = loc.get("address", "")
            for date_str, (label, flames) in CRITICAL_DATES.items():
                if ts and ts.startswith(date_str):
                    disc_id += 1
                    discoveries.append({
                        "id": f"loc-{device_id}-{disc_id}",
                        "title": f"{owner}: Location on {label} ({date_str})",
                        "category": "Locations",
                        "flames": flames,
                        "device_id": device_id,
                        "owner": owner,
                        "content": f"Location: {address or loc.get('coords', 'Unknown')}\nSource: {loc.get('source', '')}\nTime: {ts}",
                        "timestamp": ts,
                        "verified": False,
                        "tags": [label, "location"],
                        "data_type": "locations",
                    })
                    break  # Only one discovery per location

        # --- CALLS: Critical dates ---
        calls = categories.get("calls", [])
        for call in calls:
            ts = call.get("timestamp", "")
            for date_str, (label, flames) in CRITICAL_DATES.items():
                if ts and ts.startswith(date_str):
                    disc_id += 1
                    discoveries.append({
                        "id": f"call-{device_id}-{disc_id}",
                        "title": f"{owner}: {call.get('direction', '')} call on {label}",
                        "category": "Communications",
                        "flames": flames,
                        "device_id": device_id,
                        "owner": owner,
                        "content": f"Direction: {call.get('direction', '')}\nStatus: {call.get('status', '')}\nDuration: {call.get('duration', '')}\nDetails: {call.get('details', '')}\nTime: {ts}",
                        "timestamp": ts,
                        "verified": False,
                        "tags": [label, "call", call.get("direction", "")],
                        "data_type": "calls",
                    })
                    break

        # --- BROWSING: Critical dates + suspicious ---
        browsing = categories.get("browsing", [])
        for b in browsing:
            ts = b.get("timestamp", "")
            title = b.get("title", "")
            url = b.get("url", "")
            text = f"{title} {url}".lower()

            matched = []
            max_flames = 0
            for term, flames in KEY_TERMS.items():
                if term.lower() in text:
                    matched.append(term)
                    max_flames = max(max_flames, flames)

            if matched and max_flames >= 2:
                disc_id += 1
                discoveries.append({
                    "id": f"browse-{device_id}-{disc_id}",
                    "title": f"{owner}: Visited '{title[:60]}'",
                    "category": "Searches",
                    "flames": max_flames,
                    "device_id": device_id,
                    "owner": owner,
                    "content": f"Title: {title}\nURL: {url}\nBrowser: {b.get('browser', '')}\nTime: {ts}",
                    "timestamp": ts,
                    "verified": False,
                    "tags": matched[:5],
                    "data_type": "browsing",
                })

    # --- CROSS-DEVICE: Find shared contacts ---
    all_contacts = {}
    for device_id, categories in cellebrite_data.items():
        dev_info = device_map.get(device_id, {})
        contacts = categories.get("contacts", [])
        for c in contacts:
            name = c.get("name", "").strip()
            if name:
                if name not in all_contacts:
                    all_contacts[name] = []
                all_contacts[name].append(device_id)

    # Find contacts on multiple devices
    for name, devices in all_contacts.items():
        unique_devices = list(set(devices))
        if len(unique_devices) > 1:
            # Check if it's a key person
            is_key = any(kp.lower() in name.lower() for kp in KEY_PEOPLE)
            flames = 3 if is_key else 1
            if flames >= 2 or len(unique_devices) >= 3:
                disc_id += 1
                discoveries.append({
                    "id": f"cross-{disc_id}",
                    "title": f"Cross-Device: '{name}' appears on {len(unique_devices)} devices",
                    "category": "Cross-Device",
                    "flames": flames,
                    "device_id": None,
                    "owner": "Multiple",
                    "content": f"Contact '{name}' found on: {', '.join(unique_devices)}",
                    "timestamp": None,
                    "verified": False,
                    "tags": ["cross-device", "shared contact", name],
                    "data_type": "contacts",
                })

    # Deduplicate: group chat messages on same date+term to avoid flood
    deduped = _deduplicate(discoveries)

    return deduped


def _deduplicate(discoveries):
    """Reduce noise: group similar chat discoveries by date+device+category."""
    seen = set()
    result = []
    for d in discoveries:
        if d.get("verified"):
            result.append(d)
            continue

        # Create a dedup key: for chats on same device+date, only keep highest flames
        if d.get("data_type") == "chats" and d.get("timestamp"):
            date = d["timestamp"][:10]
            key = f"{d['device_id']}:{date}:{','.join(sorted(d.get('tags', [])))}"
            if key in seen:
                continue
            seen.add(key)

        # For locations on same date, group
        if d.get("data_type") == "locations" and d.get("timestamp"):
            date = d["timestamp"][:10]
            key = f"loc:{d['device_id']}:{date}"
            if key in seen:
                continue
            seen.add(key)

        result.append(d)

    return result


def get_discoveries(cellebrite_data, device_map, category="all", person="all", sort="importance"):
    """Get filtered and sorted discoveries (legacy in-memory path)."""
    all_disc = scan_discoveries(cellebrite_data, device_map)
    if category != "all":
        all_disc = [d for d in all_disc if d["category"].lower() == category.lower()]
    if person != "all":
        all_disc = [d for d in all_disc if person.lower() in (d.get("owner", "") + " ".join(d.get("tags", []))).lower()]
    if sort == "importance":
        all_disc.sort(key=lambda d: (-d["flames"], -(1 if d.get("verified") else 0), d.get("timestamp") or ""))
    elif sort == "date":
        all_disc.sort(key=lambda d: (d.get("timestamp") or "9999"), reverse=True)
    elif sort == "date_asc":
        all_disc.sort(key=lambda d: (d.get("timestamp") or "9999"))
    return all_disc


def scan_discoveries_from_db(conn, device_map):
    """Scan discoveries from SQLite records table. Much faster than re-parsing markdown."""
    discoveries = list(VERIFIED_DISCOVERIES)
    disc_id = 100
    
    # Create cursor for database queries
    cur = conn.cursor()

    # Build term patterns for SQL LIKE queries (3-flame and 2-flame terms only)
    high_terms_3 = ["trusted build", "Gold Hill", "adjudication", "Conan", "Hayes", "Griswold", "ballot image"]
    high_terms_2 = ["Dominion", "MCUA", "M.C.U.A", "forensic image", "election fraud",
                    "voting system", "Secretary of State", "Dominion Voting", "election security"]

    # Critical dates
    critical_dates_list = list(CRITICAL_DATES.items())

    for device_id, info in device_map.items():
        owner = info.get("owner", device_id)

        # --- 3-flame term matches in chats/emails (SQL LIKE) ---
        for term in high_terms_3:
            rows = cur.execute(
                "SELECT data, timestamp, category FROM records WHERE device_id=%s AND category IN ('chats','emails') AND searchable ILIKE %s LIMIT 50",
                (device_id, f"%{term}%")
            ).fetchall()
            seen_dates = set()
            for r in rows:
                rec = json.loads(r["data"])
                ts = r["timestamp"] or ""
                date_key = ts[:10] if ts else "nodate"
                if date_key in seen_dates:
                    continue
                seen_dates.add(date_key)
                disc_id += 1
                body = rec.get("body", rec.get("subject", rec.get("preview", "")))[:500]
                cat_label = "Communications"
                discoveries.append({
                    "id": f"term3-{device_id}-{disc_id}",
                    "title": f"{owner}: {'Email' if r['category']=='emails' else 'Message'} mentioning '{term}'",
                    "category": cat_label, "flames": 3, "device_id": device_id,
                    "owner": owner, "content": body, "timestamp": ts,
                    "verified": False, "tags": [term],
                    "data_type": r["category"], "source_app": rec.get("source_app", ""),
                })

        # --- 2-flame term matches ---
        for term in high_terms_2:
            rows = cur.execute(
                "SELECT data, timestamp, category FROM records WHERE device_id=%s AND category IN ('chats','emails') AND searchable ILIKE %s LIMIT 20",
                (device_id, f"%{term}%")
            ).fetchall()
            seen_dates = set()
            for r in rows:
                rec = json.loads(r["data"])
                ts = r["timestamp"] or ""
                date_key = ts[:10] if ts else "nodate"
                if date_key in seen_dates:
                    continue
                seen_dates.add(date_key)
                disc_id += 1
                body = rec.get("body", rec.get("subject", rec.get("preview", "")))[:500]
                discoveries.append({
                    "id": f"term2-{device_id}-{disc_id}",
                    "title": f"{owner}: {'Email' if r['category']=='emails' else 'Message'} mentioning '{term}'",
                    "category": "Communications", "flames": 2, "device_id": device_id,
                    "owner": owner, "content": body, "timestamp": ts,
                    "verified": False, "tags": [term],
                    "data_type": r["category"], "source_app": rec.get("source_app", ""),
                })

        # --- Critical date messages ---
        for date_str, (label, flames) in critical_dates_list:
            rows = cur.execute(
                "SELECT data, category FROM records WHERE device_id=%s AND category='chats' AND timestamp LIKE %s LIMIT 5",
                (device_id, f"{date_str}%")
            ).fetchall()
            for r in rows[:3]:  # Max 3 per date per device
                rec = json.loads(r["data"])
                body = rec.get("body", "")[:500]
                if len(body) < 10:
                    continue
                disc_id += 1
                discoveries.append({
                    "id": f"date-{device_id}-{disc_id}",
                    "title": f"{owner}: Message on {label} ({date_str})",
                    "category": "Communications", "flames": flames, "device_id": device_id,
                    "owner": owner, "content": body, "timestamp": f"{date_str}T00:00:00",
                    "verified": False, "tags": [label, date_str],
                    "data_type": "chats", "source_app": rec.get("source_app", ""),
                })

        # --- Critical date calls ---
        for date_str, (label, flames) in critical_dates_list:
            cur.execute(
            "SELECT COUNT(*) as count FROM records WHERE device_id=%s AND category='calls' AND timestamp LIKE %s",
                (device_id, f"{date_str}%")
            ).fetchone()['count']
            if count:
                disc_id += 1
                discoveries.append({
                    "id": f"calls-{device_id}-{date_str}-{disc_id}",
                    "title": f"{owner}: {count} calls on {label} ({date_str})",
                    "category": "Communications", "flames": flames, "device_id": device_id,
                    "owner": owner, "content": f"{count} phone calls recorded on {label}",
                    "timestamp": f"{date_str}T00:00:00",
                    "verified": False, "tags": [label, "calls"],
                    "data_type": "calls",
                })

        # --- Critical date locations ---
        for date_str, (label, flames) in critical_dates_list:
            rows = cur.execute(
                "SELECT data FROM records WHERE device_id=%s AND category='locations' AND timestamp LIKE %s LIMIT 3",
                (device_id, f"{date_str}%")
            ).fetchall()
            if rows:
                locs = [json.loads(r["data"]) for r in rows]
                addrs = [l.get("address", "") for l in locs if l.get("address")]
                disc_id += 1
                discoveries.append({
                    "id": f"loc-{device_id}-{date_str}-{disc_id}",
                    "title": f"{owner}: Location on {label} ({date_str})",
                    "category": "Locations", "flames": flames, "device_id": device_id,
                    "owner": owner,
                    "content": f"Locations: {', '.join(addrs[:5]) or 'GPS coordinates recorded'} ({len(rows)}+ entries)",
                    "timestamp": f"{date_str}T00:00:00",
                    "verified": False, "tags": [label, "location"],
                    "data_type": "locations",
                })

        # --- Suspicious searches ---
        rows = cur.execute(
            "SELECT data, timestamp FROM records WHERE device_id=%s AND category='searches'", (device_id,)
        ).fetchall()
        for r in rows:
            rec = json.loads(r["data"])
            query = rec.get("query", "")
            q_lower = query.lower()
            matched = []
            max_flames = 0
            for term in high_terms_3 + high_terms_2:
                if term.lower() in q_lower:
                    matched.append(term)
                    max_flames = max(max_flames, 3 if term in high_terms_3 else 2)
            for s in ["how to delete", "clear history", "delete messages", "factory reset"]:
                if s in q_lower:
                    matched.append(s)
                    max_flames = 3
            if matched:
                disc_id += 1
                discoveries.append({
                    "id": f"search-{device_id}-{disc_id}",
                    "title": f"{owner}: Searched '{query[:60]}'",
                    "category": "Searches", "flames": max_flames, "device_id": device_id,
                    "owner": owner, "content": f"Search: {query}\nSource: {rec.get('source_app', '')}",
                    "timestamp": r["timestamp"],
                    "verified": False, "tags": matched[:5],
                    "data_type": "searches",
                })

        # --- Passwords ---
        pwd_cur.execute(
            "SELECT COUNT(*) as count FROM records WHERE device_id=%s AND category='passwords'", (device_id,)
        ).fetchone()['count']
        if pwd_count:
            disc_id += 1
            discoveries.append({
                "id": f"pwd-{device_id}-{disc_id}",
                "title": f"{owner}: {pwd_count} Stored Passwords Found",
                "category": "Passwords", "flames": 2, "device_id": device_id,
                "owner": owner, "content": f"Found {pwd_count} stored passwords/credentials.",
                "timestamp": None, "verified": False,
                "tags": ["passwords", "credentials"], "data_type": "passwords",
            })

    # --- Cross-device contacts ---
    all_contacts = defaultdict(set)
    rows = cur.execute("SELECT device_id, data FROM records WHERE category='contacts'").fetchall()
    for r in rows:
        rec = json.loads(r["data"])
        name = rec.get("name", "").strip()
        if name:
            all_contacts[name].add(r["device_id"])

    KEY_PEOPLE = ["Tina Peters", "Tina", "Wendi", "Woods", "Gerald Wood", "Sherronna", "Bishop",
                  "Sandra Brown", "Sandye", "Belinda", "Knisley", "Joy Quinn", "Zachary"]
    for name, devices in all_contacts.items():
        if len(devices) < 2:
            continue
        is_key = any(kp.lower() in name.lower() for kp in KEY_PEOPLE)
        flames = 3 if is_key else 1
        if flames >= 2 or len(devices) >= 3:
            disc_id += 1
            discoveries.append({
                "id": f"cross-{disc_id}",
                "title": f"Cross-Device: '{name}' on {len(devices)} devices",
                "category": "Cross-Device", "flames": flames,
                "device_id": None, "owner": "Multiple",
                "content": f"Contact '{name}' found on: {', '.join(sorted(devices))}",
                "timestamp": None, "verified": False,
                "tags": ["cross-device", "shared contact", name],
                "data_type": "contacts",
            })

    return discoveries

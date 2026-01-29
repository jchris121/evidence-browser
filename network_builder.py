"""
Network Builder — mines Cellebrite parsed data to build a relationship graph.
Cross-references contacts, calls, chats, and emails across devices.
"""
import os
import re
import json
import hashlib
from collections import defaultdict
from pathlib import Path
from legal_scanner import get_cached_legal

DATA_DIR = Path(os.path.expanduser("~/clawd/tina-legal/cellebrite-parsed"))

# Primary people and their known devices
PRIMARY_PEOPLE = {
    "Tina Peters": {"devices": ["iPhone 11", "iPhone SE Black", "iPhone 7"], "role": "defendant"},
    "Gerald Wood": {"devices": ["iPhone"], "role": "associate"},
    "Wendi Woods": {"devices": ["iPhone", "HP Desktop", "MSI Laptop"], "role": "associate"},
    "Sherronna Bishop": {"devices": ["HP Laptop"], "role": "associate"},
    "Sandra Brown": {"devices": ["Samsung", "Motorola"], "role": "associate"},
    "Belinda Knisley": {"devices": ["Phone"], "role": "colleague"},
    "Joy Quinn": {"devices": ["iPhone XR"], "role": "family"},
    "Zachary Quinn": {"devices": ["Phone"], "role": "family"},
    "Conan Hayes": {"devices": ["T-Mobile records", "Bank records"], "role": "associate"},
}

# Name aliases for fuzzy matching
NAME_ALIASES = {
    "tina peters": ["tina", "mom", "tina p"],
    "wendi woods": ["wendi", "wendi wood", "wendy woods", "wendy wood"],
    "joy quinn": ["joy"],
    "zachary quinn": ["zachary", "zach", "zach quinn"],
    "belinda knisley": ["belinda"],
    "sherronna bishop": ["sherronna"],
    "sandra brown": ["sandra", "sandye brown", "sandye"],
    "gerald wood": ["gerald", "jerry wood"],
    "conan hayes": ["conan"],
}

# Device file prefixes
DEVICE_PREFIXES = {
    "belinda-knisley": "Belinda Knisley",
    "joy-quinn": "Joy Quinn",
    "wendi-woods": "Wendi Woods",
    "zachary-quinn": "Zachary Quinn",
}


def normalize_name(name):
    """Normalize a name for matching."""
    if not name:
        return ""
    name = name.strip().lower()
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def match_primary(name):
    """Try to match a name to a primary person."""
    norm = normalize_name(name)
    if not norm or len(norm) < 3:
        return None
    
    # Direct match
    for primary in PRIMARY_PEOPLE:
        if normalize_name(primary) == norm:
            return primary
    
    # Alias match
    for primary, aliases in NAME_ALIASES.items():
        for alias in aliases:
            if norm == alias or norm == normalize_name(alias):
                # Find the properly cased primary name
                for p in PRIMARY_PEOPLE:
                    if normalize_name(p) == primary:
                        return p
    
    # Partial match (last name + first name)
    for primary in PRIMARY_PEOPLE:
        parts = normalize_name(primary).split()
        if len(parts) >= 2:
            if norm == parts[-1] and len(parts[-1]) > 3:  # Last name only if unique enough
                continue  # Skip last-name-only matches (too ambiguous)
            if all(p in norm for p in parts):
                return primary
    
    return None


def make_id(name):
    """Create a stable ID from a name."""
    return hashlib.md5(normalize_name(name).encode()).hexdigest()[:12]


def parse_contacts(filepath, device_owner):
    """Parse a contacts markdown file. Returns list of {name, source, device_owner}."""
    contacts = []
    if not filepath.exists():
        return contacts
    
    text = filepath.read_text(errors='replace')
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('- **'):
            continue
        # Pattern: - **Name** | Source: Platform
        m = re.match(r'-\s+\*\*(.+?)\*\*\s*(?:\|\s*Source:\s*(.+))?', line)
        if m:
            name = m.group(1).strip()
            source = (m.group(2) or "").strip()
            if name and name != "****" and len(name) > 1:
                contacts.append({
                    "name": name,
                    "source": source,
                    "device_owner": device_owner,
                })
    return contacts


def parse_calls(filepath, device_owner):
    """Parse calls markdown. Returns list of {timestamp, direction, status, duration, number, source}."""
    calls = []
    if not filepath.exists():
        return calls
    
    text = filepath.read_text(errors='replace')
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('- **'):
            continue
        # Pattern: - **timestamp** | Direction | Status | Duration: X | number | Source: Y
        m = re.match(
            r'-\s+\*\*(.+?)\*\*\s*\|\s*(Incoming|Outgoing)\s*\|\s*(\w+)\s*\|\s*Duration:\s*(\S*)\s*\|?\s*(.*)',
            line
        )
        if m:
            ts = m.group(1).strip()
            direction = m.group(2)
            status = m.group(3)
            duration = m.group(4)
            rest = m.group(5).strip()
            
            # Extract source if present
            source = ""
            number = ""
            if "Source:" in rest:
                parts = rest.split("Source:")
                number = parts[0].strip().strip('|').strip()
                source = parts[1].strip()
            else:
                number = rest.strip().strip('|').strip()
            
            calls.append({
                "timestamp": ts,
                "direction": direction,
                "status": status,
                "duration": duration,
                "number": number,
                "source": source,
                "device_owner": device_owner,
            })
    return calls


def parse_chats(filepath, device_owner):
    """Parse chats markdown. Returns chat threads with participants and message counts."""
    threads = []
    if not filepath.exists():
        return threads
    
    text = filepath.read_text(errors='replace')
    
    # Find chat headers
    current_platform = None
    current_participants = set()
    current_messages = 0
    current_started = None
    
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Chat header: ### Chat: Platform — Person or ### Chat: Platform
        chat_match = re.match(r'###\s+Chat:\s+(.+?)(?:\s*—\s*(.+))?$', line)
        if chat_match:
            # Save previous thread
            if current_platform and (current_participants or current_messages > 0):
                threads.append({
                    "platform": current_platform,
                    "participants": list(current_participants),
                    "message_count": current_messages,
                    "started": current_started,
                    "device_owner": device_owner,
                })
            
            current_platform = chat_match.group(1).strip()
            person = chat_match.group(2)
            current_participants = set()
            if person:
                current_participants.add(person.strip())
            current_messages = 0
            current_started = None
            i += 1
            continue
        
        # Started line
        started_match = re.match(r'\*\*Started:\*\*\s+(.+)', line)
        if started_match:
            current_started = started_match.group(1).strip()
            i += 1
            continue
        
        # Message line: - [timestamp] **Name**: message (Platform)
        msg_match = re.match(r'-\s+\[(.+?)\]\s+\*\*(.+?)\*\*:\s*(.*?)\s*\((.+?)\)$', line)
        if msg_match:
            sender = msg_match.group(2).strip()
            platform = msg_match.group(4).strip()
            if sender and sender != "****":
                current_participants.add(sender)
            current_messages += 1
            if not current_platform:
                current_platform = platform
            i += 1
            continue
        
        i += 1
    
    # Save last thread
    if current_platform and (current_participants or current_messages > 0):
        threads.append({
            "platform": current_platform,
            "participants": list(current_participants),
            "message_count": current_messages,
            "started": current_started,
            "device_owner": device_owner,
        })
    
    return threads


def parse_emails(filepath, device_owner):
    """Parse emails markdown. Returns list of {from, to, timestamp}."""
    emails = []
    if not filepath.exists():
        return emails
    
    text = filepath.read_text(errors='replace')
    
    for line in text.split('\n'):
        line = line.strip()
        # Pattern: **From:** addr → **To:** addr
        m = re.match(r'\*\*From:\*\*\s*(.*?)\s*→\s*\*\*To:\*\*\s*(.*)', line)
        if m:
            frm = m.group(1).strip()
            to = m.group(2).strip()
            emails.append({
                "from": frm,
                "to": to,
                "device_owner": device_owner,
            })
    
    return emails


def build_network():
    """Build the complete network graph from all parsed data."""
    nodes = {}  # id -> node data
    edges = defaultdict(lambda: {"types": [], "weight": 0})  # (src_id, tgt_id) -> edge
    
    all_contacts = []
    all_calls = []
    all_chats = []
    all_emails = []
    
    # Parse all device data
    for prefix, owner in DEVICE_PREFIXES.items():
        contacts_file = DATA_DIR / f"{prefix}_contacts.md"
        calls_file = DATA_DIR / f"{prefix}_calls.md"
        chats_file = DATA_DIR / f"{prefix}_chats.md"
        emails_file = DATA_DIR / f"{prefix}_emails.md"
        
        all_contacts.extend(parse_contacts(contacts_file, owner))
        all_calls.extend(parse_calls(calls_file, owner))
        all_chats.extend(parse_chats(chats_file, owner))
        all_emails.extend(parse_emails(emails_file, owner))
    
    # 1. Add primary nodes
    for name, info in PRIMARY_PEOPLE.items():
        nid = make_id(name)
        nodes[nid] = {
            "id": nid,
            "name": name,
            "type": "primary",
            "role": info["role"],
            "devices": info["devices"],
            "contact_count": 0,
            "call_count": 0,
            "message_count": 0,
            "email_count": 0,
            "appears_on": [],
        }
    
    # 2. Process contacts - find people who appear on multiple devices
    contact_by_name = defaultdict(lambda: {"devices": set(), "sources": set()})
    
    for c in all_contacts:
        name = c["name"]
        norm = normalize_name(name)
        if not norm or len(norm) < 2:
            continue
        
        # Check if this is a primary person
        primary = match_primary(name)
        if primary:
            nid = make_id(primary)
            nodes[nid]["appears_on"].append(c["device_owner"])
            nodes[nid]["contact_count"] += 1
            
            # Create edge between device owner and this primary person
            owner_primary = match_primary(c["device_owner"])
            if owner_primary and owner_primary != primary:
                owner_id = make_id(owner_primary)
                edge_key = tuple(sorted([owner_id, nid]))
                edges[edge_key]["weight"] += 1
                # Add shared_contact type
                existing_types = [t for t in edges[edge_key]["types"] if t["type"] == "shared_contact"]
                if existing_types:
                    existing_types[0]["count"] += 1
                    if c["device_owner"] not in existing_types[0].get("appears_on_devices", []):
                        existing_types[0]["appears_on_devices"].append(c["device_owner"])
                else:
                    edges[edge_key]["types"].append({
                        "type": "shared_contact",
                        "count": 1,
                        "appears_on_devices": [c["device_owner"]],
                    })
        else:
            # Track for secondary node detection
            contact_by_name[norm]["devices"].add(c["device_owner"])
            contact_by_name[norm]["sources"].add(c["source"])
            contact_by_name[norm]["display_name"] = name  # Keep original casing
    
    # 3. Create secondary nodes for people appearing on 2+ devices
    for norm_name, info in contact_by_name.items():
        if len(info["devices"]) >= 2:
            name = info.get("display_name", norm_name)
            nid = make_id(name)
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid,
                    "name": name,
                    "type": "secondary",
                    "role": "contact",
                    "devices": [],
                    "contact_count": len(info["devices"]),
                    "call_count": 0,
                    "message_count": 0,
                    "email_count": 0,
                    "appears_on": list(info["devices"]),
                }
            
            # Create edges to device owners
            for device_owner in info["devices"]:
                owner_primary = match_primary(device_owner)
                if owner_primary:
                    owner_id = make_id(owner_primary)
                    edge_key = tuple(sorted([owner_id, nid]))
                    edges[edge_key]["weight"] += 1
                    existing_types = [t for t in edges[edge_key]["types"] if t["type"] == "shared_contact"]
                    if not existing_types:
                        edges[edge_key]["types"].append({
                            "type": "shared_contact",
                            "count": 1,
                            "appears_on_devices": list(info["devices"]),
                        })
    
    # 4. Process calls - count calls per device owner
    for call in all_calls:
        owner = call["device_owner"]
        owner_primary = match_primary(owner)
        if owner_primary:
            owner_id = make_id(owner_primary)
            nodes[owner_id]["call_count"] += 1
    
    # 5. Process chats - extract relationships from chat participants
    for thread in all_chats:
        owner = thread["device_owner"]
        owner_primary = match_primary(owner)
        if not owner_primary:
            continue
        owner_id = make_id(owner_primary)
        
        for participant in thread["participants"]:
            if not participant or participant == "****":
                continue
            
            primary = match_primary(participant)
            if primary and primary != owner_primary:
                target_id = make_id(primary)
                nodes[target_id]["message_count"] += thread["message_count"]
                edge_key = tuple(sorted([owner_id, target_id]))
                edges[edge_key]["weight"] += thread["message_count"]
                
                existing = [t for t in edges[edge_key]["types"] if t["type"] == "chat" and t.get("platform") == thread["platform"]]
                if existing:
                    existing[0]["message_count"] += thread["message_count"]
                else:
                    edges[edge_key]["types"].append({
                        "type": "chat",
                        "platform": thread["platform"],
                        "message_count": thread["message_count"],
                        "date_range": thread.get("started", ""),
                    })
            else:
                # Check if secondary node exists
                norm = normalize_name(participant)
                target_id = make_id(participant)
                if target_id in nodes:
                    nodes[target_id]["message_count"] += thread["message_count"]
                    edge_key = tuple(sorted([owner_id, target_id]))
                    edges[edge_key]["weight"] += thread["message_count"]
                    existing = [t for t in edges[edge_key]["types"] if t["type"] == "chat"]
                    if existing:
                        existing[0]["message_count"] += thread["message_count"]
                    else:
                        edges[edge_key]["types"].append({
                            "type": "chat",
                            "platform": thread["platform"],
                            "message_count": thread["message_count"],
                        })
                elif thread["message_count"] >= 5:
                    # Create secondary node for active chat participants
                    nodes[target_id] = {
                        "id": target_id,
                        "name": participant,
                        "type": "secondary",
                        "role": "chat_contact",
                        "devices": [],
                        "contact_count": 0,
                        "call_count": 0,
                        "message_count": thread["message_count"],
                        "email_count": 0,
                        "appears_on": [owner],
                    }
                    edge_key = tuple(sorted([owner_id, target_id]))
                    edges[edge_key]["weight"] += thread["message_count"]
                    edges[edge_key]["types"].append({
                        "type": "chat",
                        "platform": thread["platform"],
                        "message_count": thread["message_count"],
                    })
    
    # 6. Add cross-device edges between primary people who share contacts
    # Connect device owners to each other based on shared contacts
    primary_ids = [make_id(p) for p in PRIMARY_PEOPLE]
    for norm_name, info in contact_by_name.items():
        device_owners = list(info["devices"])
        if len(device_owners) >= 2:
            for i in range(len(device_owners)):
                for j in range(i + 1, len(device_owners)):
                    owner_a = match_primary(device_owners[i])
                    owner_b = match_primary(device_owners[j])
                    if owner_a and owner_b and owner_a != owner_b:
                        id_a = make_id(owner_a)
                        id_b = make_id(owner_b)
                        edge_key = tuple(sorted([id_a, id_b]))
                        # Only add if not already there
                        existing = [t for t in edges[edge_key]["types"] if t["type"] == "shared_contact"]
                        if existing:
                            existing[0]["count"] += 1
                        else:
                            edges[edge_key]["types"].append({
                                "type": "shared_contact",
                                "count": 1,
                                "appears_on_devices": device_owners,
                            })
                            edges[edge_key]["weight"] += 1
    
    # 7. Add case file mentions from legal scanner
    person_files, _ = get_cached_legal()
    for nid, node in nodes.items():
        name = node["name"]
        case_files = person_files.get(name, [])
        node["case_files"] = case_files[:50]  # Top 50 most-mentioned files
        node["case_file_count"] = len(case_files)
        node["total_mentions"] = sum(f["mentions"] for f in case_files)
    
    # 8. Deduplicate appears_on
    for nid, node in nodes.items():
        node["appears_on"] = list(set(node["appears_on"]))
    
    # Build edge list
    edge_list = []
    for (src, tgt), data in edges.items():
        if data["weight"] > 0:
            edge_list.append({
                "source": src,
                "target": tgt,
                "types": data["types"],
                "weight": data["weight"],
            })
    
    # Sort edges by weight
    edge_list.sort(key=lambda e: e["weight"], reverse=True)
    
    return {
        "nodes": list(nodes.values()),
        "edges": edge_list,
    }


def get_person_details(person_id, network_data):
    """Get detailed info for a specific person."""
    node = None
    for n in network_data["nodes"]:
        if n["id"] == person_id:
            node = n
            break
    
    if not node:
        return None
    
    # Find all connections
    connections = []
    for edge in network_data["edges"]:
        if edge["source"] == person_id or edge["target"] == person_id:
            other_id = edge["target"] if edge["source"] == person_id else edge["source"]
            other_node = None
            for n in network_data["nodes"]:
                if n["id"] == other_id:
                    other_node = n
                    break
            if other_node:
                connections.append({
                    "person": other_node,
                    "edge": edge,
                })
    
    connections.sort(key=lambda c: c["edge"]["weight"], reverse=True)
    
    return {
        "person": node,
        "connections": connections,
        "total_connections": len(connections),
    }


# Cache
_network_cache = None

def get_cached_network():
    global _network_cache
    if _network_cache is None:
        _network_cache = build_network()
    return _network_cache


if __name__ == "__main__":
    n = build_network()
    print(f"{len(n['nodes'])} nodes, {len(n['edges'])} edges")
    print("\nPrimary nodes:")
    for node in n["nodes"]:
        if node["type"] == "primary":
            print(f"  {node['name']}: contacts={node['contact_count']}, calls={node['call_count']}, msgs={node['message_count']}")
    print(f"\nSecondary nodes: {sum(1 for n in n['nodes'] if n['type'] == 'secondary')}")
    print(f"\nTop edges:")
    for e in n["edges"][:10]:
        src = next((n["name"] for n in n["nodes"] if n["id"] == e["source"]), e["source"])
        tgt = next((n["name"] for n in n["nodes"] if n["id"] == e["target"]), e["target"])
        types = ", ".join(t["type"] for t in e["types"])
        print(f"  {src} ↔ {tgt}: weight={e['weight']} [{types}]")

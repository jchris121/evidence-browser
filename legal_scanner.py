"""
Legal Case File Scanner — scans extracted text from legal case files
for mentions of key people, building a case_files index per person.
"""
import os
import re
import time
from pathlib import Path
from collections import defaultdict

LEGAL_BASE = Path(os.path.expanduser("~/clawd/tina-legal"))

# Case directories: (label, case_id, dir with PDFs, dir with TXTs)
CASE_DIRS = [
    {
        "case_id": "22CR371",
        "label": "Criminal Case 22CR371",
        "case_type": "criminal",
        "pdf_dir": LEGAL_BASE / "case-22CR371",
        "txt_dirs": [
            LEGAL_BASE / "case-22CR371",           # .txt alongside .pdf
            LEGAL_BASE / "extracted-text" / "case-22CR371",
        ],
    },
    {
        "case_id": "24CA1951",
        "label": "State Appeal 24CA1951",
        "case_type": "appeal",
        "pdf_dir": LEGAL_BASE / "appeal-24CA1951",
        "txt_dirs": [
            LEGAL_BASE / "appeal-24CA1951",
            LEGAL_BASE / "extracted-text" / "appeal-24CA1951",
        ],
    },
    {
        "case_id": "25cv00425",
        "label": "Federal Habeas 25cv00425",
        "case_type": "habeas",
        "pdf_dir": LEGAL_BASE / "habeas-25cv00425",
        "txt_dirs": [
            LEGAL_BASE / "habeas-25cv00425",
            LEGAL_BASE / "extracted-text" / "habeas-25cv00425",
        ],
    },
    {
        "case_id": "ai-analysis",
        "label": "AI Analysis",
        "case_type": "analysis",
        "pdf_dir": LEGAL_BASE / "ai-analysis",
        "txt_dirs": [
            LEGAL_BASE / "ai-analysis",
        ],
    },
]

# People to search for — name variants
SEARCH_NAMES = {
    "Tina Peters": [
        r"\bTina\s+Peters\b", r"\bMs\.?\s+Peters\b", r"\bPeters\b",
        r"\bDefendant\s+Peters\b", r"\bPetitioner\s+Peters\b",
    ],
    "Gerald Wood": [
        r"\bGerald\s+Wood\b", r"\bJerry\s+Wood\b", r"\bMr\.?\s+Wood\b",
        r"\bGerald\b(?=.*\bWood\b)",
    ],
    "Wendi Woods": [
        r"\bWendi\s+Wood(?:s)?\b", r"\bWendy\s+Wood(?:s)?\b",
    ],
    "Sherronna Bishop": [
        r"\bSherronna\s+Bishop\b", r"\bBishop\b",
    ],
    "Sandra Brown": [
        r"\bSandra\s+Brown\b", r"\bSandye?\s+Brown\b",
    ],
    "Belinda Knisley": [
        r"\bBelinda\s+Knisley\b", r"\bKnisley\b",
    ],
    "Joy Quinn": [
        r"\bJoy\s+Quinn\b",
    ],
    "Zachary Quinn": [
        r"\bZachary\s+Quinn\b", r"\bZach(?:ary)?\s+Quinn\b",
    ],
    "Conan Hayes": [
        r"\bConan\s+Hayes\b", r"\bHayes\b",
    ],
    # Additional key figures in the case
    "Robert Cynkar": [r"\bCynkar\b", r"\bRobert\s+Cynkar\b"],
    "Matt Crane": [r"\bMatt\s+Crane\b", r"\bCrane\b"],
    "Wayne Williams": [r"\bWayne\s+Williams\b"],
    "Brandi Bantz": [r"\bBrandi\s+Bantz\b", r"\bBantz\b"],
    "Jena Griswold": [r"\bGriswold\b", r"\bJena\s+Griswold\b"],
    "Phil Weiser": [r"\bWeiser\b", r"\bPhil\s+Weiser\b"],
    "Daniel Rubinstein": [r"\bRubinstein\b"],
    "Robert Zafft": [r"\bZafft\b"],
    "Matthew Barrett": [r"\bBarrett\b", r"\bJudge\s+Barrett\b"],
}

# Compile patterns
_COMPILED = {}
for person, patterns in SEARCH_NAMES.items():
    _COMPILED[person] = [re.compile(p, re.IGNORECASE) for p in patterns]


def _find_txt_files(case_info):
    """Find all .txt/.md files for a case."""
    files = {}  # basename -> full path (dedup)
    for txt_dir in case_info["txt_dirs"]:
        if not txt_dir.exists():
            continue
        for f in txt_dir.rglob("*.txt"):
            key = f.stem
            if key not in files:
                files[key] = f
        for f in txt_dir.rglob("*.md"):
            key = f.stem
            if key not in files:
                files[key] = f
    return files


def _find_pdf_for(txt_path, case_info):
    """Given a txt file, find the corresponding PDF."""
    stem = txt_path.stem
    pdf_dir = case_info["pdf_dir"]
    if not pdf_dir.exists():
        return None
    
    # Search recursively
    for f in pdf_dir.rglob(f"{stem}.pdf"):
        return str(f)
    # Try with glob pattern for close matches
    for f in pdf_dir.rglob("*.pdf"):
        if f.stem == stem:
            return str(f)
    return None


def _count_mentions(text, person):
    """Count mentions of a person in text."""
    total = 0
    for pattern in _COMPILED.get(person, []):
        total += len(pattern.findall(text))
    return total


def scan_case_files():
    """
    Scan all legal case files for person mentions.
    Returns:
      - person_files: {person_name: [{filename, case, case_type, path, pdf_path, mentions}]}
      - case_index: {case_id: {label, case_type, files: [{filename, path, pdf_path, size}]}}
    """
    t0 = time.time()
    person_files = defaultdict(list)
    case_index = {}
    
    for case_info in CASE_DIRS:
        case_id = case_info["case_id"]
        case_index[case_id] = {
            "label": case_info["label"],
            "case_type": case_info["case_type"],
            "case_id": case_id,
            "files": [],
        }
        
        txt_files = _find_txt_files(case_info)
        
        for stem, txt_path in txt_files.items():
            try:
                text = txt_path.read_text(errors='replace')
            except Exception:
                continue
            
            if len(text.strip()) < 20:
                continue
            
            pdf_path = _find_pdf_for(txt_path, case_info)
            file_ext = txt_path.suffix
            display_name = txt_path.stem
            # Clean up display name
            if display_name.endswith("_analysis"):
                display_name = display_name.replace("_analysis", "")
            
            file_entry = {
                "filename": display_name + (file_ext if file_ext != '.txt' else '.pdf' if pdf_path else file_ext),
                "txt_path": str(txt_path),
                "pdf_path": pdf_path,
                "size": len(text),
                "case_id": case_id,
            }
            case_index[case_id]["files"].append(file_entry)
            
            # Scan for each person
            for person in SEARCH_NAMES:
                mentions = _count_mentions(text, person)
                if mentions > 0:
                    person_files[person].append({
                        "filename": file_entry["filename"],
                        "case": case_id,
                        "case_type": case_info["case_type"],
                        "path": str(txt_path),
                        "pdf_path": pdf_path,
                        "mentions": mentions,
                    })
        
        # Sort files in case index
        case_index[case_id]["files"].sort(key=lambda f: f["filename"])
        case_index[case_id]["file_count"] = len(case_index[case_id]["files"])
    
    # Sort person files by mention count desc
    for person in person_files:
        person_files[person].sort(key=lambda f: f["mentions"], reverse=True)
    
    elapsed = time.time() - t0
    print(f"[legal_scanner] Scanned {sum(c['file_count'] for c in case_index.values())} files in {elapsed:.1f}s")
    
    return dict(person_files), case_index


# Cache
_legal_cache = None

def get_cached_legal():
    global _legal_cache
    if _legal_cache is None:
        _legal_cache = scan_case_files()
    return _legal_cache


def get_person_case_files(person_name):
    """Get case files mentioning a person."""
    person_files, _ = get_cached_legal()
    return person_files.get(person_name, [])


def get_case_index():
    """Get the full case index."""
    _, case_index = get_cached_legal()
    return case_index


def read_legal_file(filepath):
    """Read a legal text file."""
    p = Path(filepath)
    if not p.exists():
        return None
    if not str(p).startswith(str(LEGAL_BASE)):
        return None  # Security: only serve files under tina-legal
    return p.read_text(errors='replace')


if __name__ == "__main__":
    person_files, case_index = scan_case_files()
    print("\n=== Cases ===")
    for cid, info in case_index.items():
        print(f"  {info['label']}: {info['file_count']} files")
    print("\n=== Person Mentions ===")
    for person, files in sorted(person_files.items(), key=lambda x: sum(f['mentions'] for f in x[1]), reverse=True):
        total = sum(f['mentions'] for f in files)
        print(f"  {person}: {total} mentions across {len(files)} files")
        for f in files[:3]:
            print(f"    - {f['filename']} ({f['case']}): {f['mentions']} mentions")

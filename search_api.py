"""RAG semantic search + Ollama chat integration.
Loads embedding cache directly (no subprocess) for speed."""
import json
import time
import urllib.request
import numpy as np
from pathlib import Path

RAG_DIR = Path.home() / "clawd/rag"
CACHE_DIR = RAG_DIR / "cache"
OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

# Cached in memory
_emb_matrix = None
_meta = None
_contents = None


def _load_cache():
    global _emb_matrix, _meta, _contents
    if _emb_matrix is not None:
        return
    emb_file = CACHE_DIR / "embeddings.npy"
    meta_file = CACHE_DIR / "metadata.json"
    contents_file = CACHE_DIR / "contents.json"
    if not emb_file.exists():
        raise RuntimeError("RAG cache not built. Run: cd ~/clawd/rag && python3 search.py 'test' first")
    _emb_matrix = np.load(emb_file)
    with open(meta_file) as f:
        _meta = json.load(f)
    with open(contents_file) as f:
        _contents = json.load(f)
    # Pre-normalize docs
    norms = np.linalg.norm(_emb_matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    _emb_matrix = _emb_matrix / norms
    print(f"RAG cache loaded: {len(_contents):,} chunks")


def _get_embedding(text: str) -> np.ndarray:
    data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings", data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return np.array(result.get("embedding", []), dtype=np.float32)


def rag_search(query: str, top_k: int = 10, threshold: float = 0.3):
    """Semantic search against RAG embeddings. Returns list of results."""
    t0 = time.time()
    _load_cache()

    q_emb = _get_embedding(query)
    if len(q_emb) == 0:
        return {"results": [], "error": "Failed to get embedding"}

    q_norm = q_emb / (np.linalg.norm(q_emb) + 1e-10)
    scores = _emb_matrix @ q_norm

    mask = scores >= threshold
    if not np.any(mask):
        return {"results": [], "stats": {"query": query, "total_time": round(time.time() - t0, 2), "results": 0}}

    if np.sum(mask) <= top_k:
        top_indices = np.where(mask)[0]
    else:
        top_indices = np.argpartition(scores, -top_k)[-top_k:]

    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    results = []
    for idx in top_indices:
        idx = int(idx)
        results.append({
            "source": _meta["sources"][idx],
            "filename": Path(_meta["sources"][idx]).name if _meta["sources"][idx] else "",
            "chunk": _meta["chunk_idxs"][idx],
            "score": round(float(scores[idx]), 4),
            "content": _contents[idx],
        })

    return {
        "results": results,
        "stats": {
            "query": query,
            "total_time": round(time.time() - t0, 2),
            "docs_scanned": len(scores),
            "results": len(results),
        }
    }


def chat_with_evidence(question: str, model: str = "qwen2.5:72b", top_k: int = 10, device_scope: str = None):
    """RAG search + LLM chat. Returns answer with sources."""
    # 1. RAG search
    rag_result = rag_search(question, top_k=top_k)
    sources = rag_result.get("results", [])

    # Filter by device scope if provided
    if device_scope and sources:
        sources = [s for s in sources if device_scope.lower() in (s.get("source", "") + s.get("filename", "")).lower()] or sources[:top_k]

    # 2. Build context from top results
    context_parts = []
    for i, s in enumerate(sources[:top_k]):
        context_parts.append(f"[Source {i+1}: {s.get('filename', 'unknown')} (score: {s['score']})]\n{s['content'][:800]}")

    context = "\n\n".join(context_parts)

    # 3. Map model shorthand
    model_map = {
        "fast": "llama3.2:3b",
        "deep": "qwen2.5:72b",
        "code": "qwen2.5-coder:32b",
    }
    actual_model = model_map.get(model, model)

    # 4. Call Ollama
    messages = [
        {
            "role": "system",
            "content": (
                "You are a forensic evidence analyst reviewing digital forensic extractions from the Tina Peters case. "
                "Answer questions using ONLY the provided evidence context. "
                "Always cite which source file and content supports your answer. "
                "If the evidence doesn't contain relevant information, say so clearly. "
                "Be precise and factual. Format your answer with clear paragraphs."
            )
        },
        {
            "role": "user",
            "content": f"Evidence context from forensic extractions:\n\n{context}\n\n---\n\nQuestion: {question}"
        }
    ]

    payload = json.dumps({
        "model": actual_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 2000}
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            answer = result.get("message", {}).get("content", "No response generated")
    except Exception as e:
        answer = f"Error calling {actual_model}: {str(e)}"

    return {
        "answer": answer,
        "model": actual_model,
        "sources": [{"file": s.get("filename", ""), "source": s.get("source", ""), "snippet": s["content"][:200], "score": s["score"]} for s in sources[:top_k]],
        "stats": rag_result.get("stats", {})
    }

"""
PART B, steps 3-5: pinned answers, hybrid search, relevance gate.

Hybrid search = two different searches whose rankings are merged:
  * meaning search  - cosine similarity between the question's embedding and every chunk's embedding
  * keyword search  - BM25 (exact words, good for names like "Tikarpada")
  * merge           - Reciprocal Rank Fusion: each chunk gets 1/(60+rank) from each list, summed.
                      Chunks ranked high in BOTH lists come out on top.
Gate 1: if even the best chunk is not similar enough to the question, we stop here and the
LLM is never called -> no chance to invent an answer.
"""
import json
import logging

import numpy as np

import config
from core.bm25 import BM25
from core.embedder import get_embedder
from core.textutil import tokenize

log = logging.getLogger("van_mitra.retriever")


class Retriever:
    def __init__(self):
        self.load()

    # ------------------------------------------------------------ load
    def load(self):
        idx = config.INDEX_DIR
        if not (idx / "chunks.json").exists():
            raise RuntimeError("Knowledge index not found. Run:  python build_index.py")
        self.meta = json.loads((idx / "meta.json").read_text(encoding="utf-8"))
        self.chunks = json.loads((idx / "chunks.json").read_text(encoding="utf-8"))
        self.pinned = json.loads((idx / "pinned_index.json").read_text(encoding="utf-8"))
        self.bm25 = BM25([c["tokens"] for c in self.chunks])
        self.pinned_tokens = [set(p["tokens"]) for p in self.pinned]

        self.emb = None
        self.E = self.P = None
        if self.meta.get("embed_model") and (idx / "embeddings.npy").exists():
            emb = get_embedder()
            if emb is not None and emb.name == self.meta["embed_model"]:
                self.emb = emb
                self.E = np.load(idx / "embeddings.npy")
                if (idx / "pinned_embeddings.npy").exists():
                    self.P = np.load(idx / "pinned_embeddings.npy")
            else:
                log.warning("Index has embeddings but the model can't be loaded -> keyword-only mode")
        self.mode = "hybrid" if self.emb is not None else "keyword-only"
        log.info("Knowledge loaded: %d chunks, %d pinned questions, mode=%s",
                 len(self.chunks), len(self.pinned), self.mode)

    # ------------------------------------------------------------ pinned answers
    def match_pinned(self, question):
        if not self.pinned:
            return None
        if self.emb is not None and self.P is not None:
            # compare question-to-question (no query prefix on either side for symmetric similarity)
            qv = self.emb.embed_docs([question])[0]
            sims = self.P @ qv
            i = int(np.argmax(sims))
            score, thr, how = float(sims[i]), config.PINNED_THRESHOLD, "cosine"
        else:
            qt = set(tokenize(question))
            best, i = 0.0, 0
            for j, pt in enumerate(self.pinned_tokens):
                if qt and pt:
                    jac = len(qt & pt) / len(qt | pt)
                    if jac > best:
                        best, i = jac, j
            score, thr, how = best, config.PINNED_THRESHOLD_KEYWORD, "word-overlap"
        p = self.pinned[i]
        return {"id": p["id"], "matched_question": p["question"], "answer": p["answer"],
                "score": round(score, 3), "threshold": thr, "method": how, "hit": score >= thr}

    # ------------------------------------------------------------ hybrid search + gate
    def search(self, question):
        q_tokens = tokenize(question)
        bm = np.array(self.bm25.scores(q_tokens), dtype=np.float32)
        bm_rank = _ranks(bm)

        qvec = None
        if self.emb is not None:
            qvec = self.emb.embed_query(question)
            cos = self.E @ qvec
            cos_rank = _ranks(cos)
            rrf = 1.0 / (config.RRF_K + cos_rank) + 1.0 / (config.RRF_K + bm_rank)
            # chunks with zero keyword match get no BM25 credit
            rrf -= np.where(bm > 0, 0, 1.0 / (config.RRF_K + bm_rank))
            order = np.argsort(-rrf)
            best_cos = float(cos.max())
            gate = {"method": "best cosine similarity", "value": round(best_cos, 3),
                    "threshold": config.GATE_COSINE, "passed": best_cos >= config.GATE_COSINE}
        else:
            cos = None
            rrf = 1.0 / (config.RRF_K + bm_rank)
            order = np.argsort(-bm)
            top = int(order[0])
            cover = self.bm25.coverage(q_tokens, top) if bm[top] > 0 else 0.0
            gate = {"method": "keyword coverage of best passage", "value": round(cover, 3),
                    "threshold": config.GATE_BM25_FALLBACK, "passed": cover >= config.GATE_BM25_FALLBACK}

        results = []
        for i in order[: config.TOP_K]:
            i = int(i)
            if cos is None and bm[i] <= 0:
                continue
            c = self.chunks[i]
            results.append({
                "id": c["id"], "file": c["file"], "page": c.get("page"), "section": c.get("section", ""),
                "text": c["text"],
                "cosine": None if cos is None else round(float(cos[i]), 3),
                "bm25": round(float(bm[i]), 2),
                "rrf": round(float(rrf[i]), 4),
            })
        return {"query_tokens": q_tokens, "results": results, "gate": gate, "mode": self.mode, "qvec": qvec}

    def idf(self):
        return self.bm25.idf


def _ranks(scores):
    """rank 1 = best."""
    order = np.argsort(-scores)
    r = np.empty(len(scores), dtype=np.float32)
    r[order] = np.arange(1, len(scores) + 1)
    return r

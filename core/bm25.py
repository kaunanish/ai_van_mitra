"""
BM25 keyword search (the classic search-engine formula), written out in full
so there is nothing hidden.

For each query word that appears in a passage, BM25 adds:
    idf(word) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len/avg_len))
  idf  - rare words (e.g. "gharial") count much more than common ones ("forest")
  tf   - how many times the word appears in the passage (with diminishing returns)
  len  - long passages are slightly penalised so they don't win just by being long
It catches exact names ("Satkosia", "Tikarpada") that meaning-search can blur.
"""
import math
from collections import Counter


class BM25:
    def __init__(self, tokenized_docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in tokenized_docs]
        self.lens = [len(d) for d in tokenized_docs]
        self.avg_len = (sum(self.lens) / len(self.lens)) if self.lens else 1.0
        n = len(tokenized_docs)
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, query_tokens):
        out = []
        for d, L in zip(self.docs, self.lens):
            s = 0.0
            for w in query_tokens:
                tf = d.get(w)
                if not tf:
                    continue
                s += self.idf[w] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * L / self.avg_len))
            out.append(s)
        return out

    def coverage(self, query_tokens, doc_index):
        """Share (0..1) of the query's information (idf-weighted) present in one passage.
        Used as the relevance gate when no embedding model is available."""
        q = [w for w in set(query_tokens)]
        if not q:
            return 0.0
        max_idf = max(self.idf.values()) if self.idf else 1.0
        total = sum(self.idf.get(w, max_idf) for w in q)  # unknown word = maximally informative & missing
        hit = sum(self.idf[w] for w in q if w in self.docs[doc_index])
        return hit / total if total else 0.0

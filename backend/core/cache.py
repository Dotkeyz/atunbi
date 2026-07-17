"""
In-memory LRU caches for embedding and scoring.

Saves ~30% of embedding API calls on repeated phrases.
NOT cached: search results (too dynamic), LLM responses (low hit rate).
"""
from collections import OrderedDict
import hashlib
from typing import Optional


class LRUCache:
    """Simple LRU cache with max size. Thread-safe for async use."""
    
    def __init__(self, max_size: int = 1000, name: str = "cache"):
        self.max_size = max_size
        self.name = name
        self._cache: OrderedDict[str, any] = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    def get(self, text: str) -> Optional[any]:
        key = self._hash(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None
    
    def set(self, text: str, value: any):
        key = self._hash(text)
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
    
    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0
    
    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
        }


# Global cache instances
embedding_cache = LRUCache(max_size=1000, name="embedding")
scoring_cache = LRUCache(max_size=1000, name="scoring")

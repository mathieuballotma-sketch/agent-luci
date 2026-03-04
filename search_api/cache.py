import time
import hashlib
from typing import Any, Optional

class SimpleCache:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._store = {}

    def _key(self, query: str) -> str:
        return hashlib.md5(query.encode()).hexdigest()

    def get(self, query: str) -> Optional[Any]:
        key = self._key(query)
        if key in self._store:
            value, timestamp = self._store[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self._store[key]
        return None

    def set(self, query: str, value: Any):
        key = self._key(query)
        self._store[key] = (value, time.time())

    def clear(self):
        self._store.clear()
"""Bounded, in-process cache for validated generations."""
from collections import OrderedDict
from time import monotonic


class GenerationCache:
    def __init__(self, ttl: float, capacity: int = 128):
        self.ttl = ttl
        self.capacity = capacity
        self.entries = OrderedDict()

    def get(self, key):
        entry = self.entries.pop(key, None)
        if entry is not None and entry[0] > monotonic():
            self.entries[key] = entry
            return entry[1]
        return None

    def put(self, key, titles):
        if self.ttl <= 0:
            return
        self.entries[key] = (monotonic() + self.ttl, tuple(titles))
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)

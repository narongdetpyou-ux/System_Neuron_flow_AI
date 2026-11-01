"""Small in-memory rate limits (token buckets). They reset when the process restarts, which is fine
for their purpose: slowing down abuse of a single-owner pilot, not billing or quotas."""

from collections import OrderedDict
import math
import threading
import time


class TokenBucket:
    def __init__(self, capacity, per_seconds, clock):
        self.capacity = float(capacity)
        self.rate = capacity / per_seconds
        self.tokens = float(capacity)
        self.clock = clock
        self.updated = clock()

    def _refill(self):
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def available(self):
        self._refill()
        return self.tokens >= 1

    def take(self):
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def retry_after(self):
        """Whole seconds until one token is back (at least 1)."""
        return max(1, math.ceil((1 - self.tokens) / self.rate))


class RateLimiter:
    """One bucket per client, plus an optional bucket shared by everyone.

    The client map is bounded (oldest entries are dropped), so many distinct clients cannot grow
    memory without limit.
    """

    def __init__(self, capacity, per_seconds, *, total_capacity=None, max_clients=1024, clock=time.monotonic):
        self.capacity, self.per_seconds, self.clock = capacity, per_seconds, clock
        self.max_clients = max_clients
        self._clients = OrderedDict()
        self._total = TokenBucket(total_capacity, per_seconds, clock) if total_capacity else None
        self._lock = threading.Lock()

    def _bucket(self, client):
        bucket = self._clients.get(client)
        if bucket is None:
            bucket = self._clients[client] = TokenBucket(self.capacity, self.per_seconds, self.clock)
            while len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)
        else:
            self._clients.move_to_end(client)
        return bucket

    def allow(self, client):
        """Take one token. Returns ``(allowed, retry_after_seconds)``."""
        with self._lock:
            bucket = self._bucket(client)
            if not bucket.available():
                return False, bucket.retry_after()
            if self._total is not None and not self._total.take():
                return False, self._total.retry_after()
            bucket.take()
            return True, 0

    def blocked(self, client):
        """True while this client has no tokens left (checked without taking one)."""
        with self._lock:
            bucket = self._clients.get(client)
            return bucket is not None and not bucket.available()

    def retry_after(self, client):
        with self._lock:
            bucket = self._clients.get(client)
            return bucket.retry_after() if bucket is not None else 1

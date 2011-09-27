from piecrust.exceptions import ImproperlyConfigured
try:
    import pylibmc
except ImportError:
    pylibmc = None


class NoCache(object):
    """
    A simplified, swappable base class for caching.

    Does nothing save for simulating the cache API.
    """
    def get(self, key):
        """
        Always returns ``None``.
        """
        return None

    def set(self, key, value, timeout=60):
        """
        No-op for setting values in the cache.
        """
        pass


class MemcacheCache(NoCache):
    def __init__(self, *args, **kwargs):
        if pylibmc is None:
            raise ImproperlyConfigured("The 'pylibmc' package must be installed to use the 'MemcacheCache'.")

        self.conn = pylibmc.Client(*args, **kwargs)

    def get(self, key):
        return self.conn.get(key)

    def set(self, key, value, timeout=60):
        return self.conn.set(key, value)

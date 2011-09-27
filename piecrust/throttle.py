class BaseThrottle(object):
    """
    A simplified, swappable base class for throttling.

    Does nothing save for simulating the throttling API and implementing
    some common bits for the subclasses.

    Accepts a number of optional kwargs::

        * ``throttle_at`` - the number of requests at which the user should
          be throttled. Default is 150 requests.
        * ``timeframe`` - the length of time (in seconds) in which the user
          make up to the ``throttle_at`` requests. Default is 3600 seconds (
          1 hour).
        * ``expiration`` - the length of time to retain the times the user
          has accessed the api in the cache. Default is 604800 (1 week).
    """
    def __init__(self, throttle_at=150, timeframe=3600, expiration=None):
        self.throttle_at = throttle_at
        # In seconds, please.
        self.timeframe = timeframe

        if expiration is None:
            # Expire in a week.
            expiration = 604800

        self.expiration = int(expiration)

    def convert_identifier_to_key(self, identifier):
        """
        Takes an identifier (like a username or IP address) and converts it
        into a key usable by the cache system.
        """
        bits = []

        for char in identifier:
            if char.isalnum() or char in ['_', '.', '-']:
                bits.append(char)

        safe_string = ''.join(bits)
        return "%s_accesses" % safe_string

    def should_be_throttled(self, identifier, **kwargs):
        """
        Returns whether or not the user has exceeded their throttle limit.

        Always returns ``False``, as this implementation does not actually
        throttle the user.
        """
        return False

    def accessed(self, identifier, **kwargs):
        """
        Handles recording the user's access.

        Does nothing in this implementation.
        """
        pass

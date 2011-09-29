class PiecrustError(Exception):
    """A base exception for other piecrust-related errors."""
    pass


class Unauthorized(PiecrustError):
    """
    Used by the authentication classes to indicate when the credentials are
    invalid.
    """
    pass


class ImproperlyConfigured(PiecrustError):
    """Something isn't setup right. You should fix that."""
    pass


class HydrationError(PiecrustError):
    """Raised when there is an error hydrating data."""
    pass


class NotRegistered(PiecrustError):
    """
    Raised when the requested resource isn't registered with the ``Api`` class.
    """
    pass


class NotFound(PiecrustError):
    """
    Raised when the resource/object in question can't be found.
    """
    pass


class ApiFieldError(PiecrustError):
    """
    Raised when there is a configuration error with a ``ApiField``.
    """
    pass


class UnsupportedFormat(PiecrustError):
    """
    Raised when an unsupported serialization format is requested.
    """
    pass


class BadRequest(PiecrustError):
    """
    A generalized exception for indicating incorrect request parameters.

    Handled specially in that the message tossed by this exception will be
    presented to the end user.
    """
    pass


class BlueberryFillingFound(PiecrustError):
    pass


class InvalidFilterError(BadRequest):
    """
    Raised when the end user attempts to use a filter that has not be
    explicitly allowed.
    """
    pass


class InvalidSortError(PiecrustError):
    """
    Raised when the end user attempts to sort on a field that has not be
    explicitly allowed.
    """
    pass


class ImmediateHttpResponse(PiecrustError):
    """
    This exception is used to interrupt the flow of processing to immediately
    return a custom HttpResponse.

    Common uses include::

        * for authentication (like digest/OAuth)
        * for throttling

    """
    def __init__(self, response):
        self.response = response

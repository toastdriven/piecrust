from piecrust.exceptions import ImproperlyConfigured


class RequestWrapper(object):
    """
    Like it or leave it, the request wrapper makes other requests look like
    what the rest of piecrust expects (Django-esque).
    """
    def __init__(self, request):
        self.request = request

    def __getitem__(self, key):
        try:
            return getattr(self.request, key)
        except AttributeError, e:
            return getattr(self, key)

    def __setitem__(self, key, value):
        maybe_attr = getattr(self, key, None)

        if maybe_attr:
            if callable(maybe_attr):
                maybe_attr(value)
            else:
                maybe_attr = value

        return setattr(self.request, key, value)

    def check_valid(self):
        """
        An internal check to ensure that the wrapper responds correctly
        to all necessary attributes.
        """
        if not hasattr(request, 'method') or not isinstance(request.method, basestring):
            raise ImproperlyConfigured("'RequestWrapper' subclass requires access to 'request.method'.")

        # FIXME: More checks.

    def mangle(self):
        """
        A hook for manipulating the internal request object or faking .
        """
        pass


class ResponseGenerator(object):
    def create(self, response_obj):
        """
        Given response data (a ``PiecrustResponse`` instance), return the
        correct response for your given framework.
        """
        raise ImproperlyConfigured("You must subclass 'ResponseGenerator' & implement a 'generate_http_response' method.")


class PiecrustResponse(object):
    status_code = 200

    def __init__(self, content=None, status_code=None, **kwargs):
        self.content = content
        self.extra_data = kwargs

        if status_code is not None:
            self.status_code = status_code


class HttpOK(PiecrustResponse):
    status_code = 200


class HttpCreated(PiecrustResponse):
    status_code = 201

    def __init__(self, *args, **kwargs):
        location = ''

        if 'location' in kwargs:
            location = kwargs['location']
            del(kwargs['location'])

        super(HttpCreated, self).__init__(*args, **kwargs)
        self['Location'] = location


class HttpAccepted(PiecrustResponse):
    status_code = 202


class HttpNoContent(PiecrustResponse):
    status_code = 204


class HttpMultipleChoices(PiecrustResponse):
    status_code = 300


class HttpSeeOther(PiecrustResponse):
    status_code = 303


class HttpNotModified(PiecrustResponse):
    status_code = 304


class HttpBadRequest(PiecrustResponse):
    status_code = 400


class HttpUnauthorized(PiecrustResponse):
    status_code = 401


class HttpForbidden(PiecrustResponse):
    status_code = 403


class HttpNotFound(PiecrustResponse):
    status_code = 404


class HttpMethodNotAllowed(PiecrustResponse):
    status_code = 405


class HttpConflict(PiecrustResponse):
    status_code = 409


class HttpGone(PiecrustResponse):
    status_code = 410


class HttpApplicationError(PiecrustResponse):
    status_code = 500


class HttpNotImplemented(PiecrustResponse):
    status_code = 501


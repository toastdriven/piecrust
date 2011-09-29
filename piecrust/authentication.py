import base64
import hmac
import time
import uuid
from piecrust.exceptions import ImproperlyConfigured, Unauthorized
from piecrust.http import HttpUnauthorized
try:
    from hashlib import sha1
except ImportError:
    import sha
    sha1 = sha.sha
try:
    import python_digest
except ImportError:
    python_digest = None


class Authentication(object):
    """
    A simple base class to establish the protocol for auth.

    By default, this indicates the user is always authenticated.
    """
    def is_authenticated(self, request, **kwargs):
        """
        Identifies if the user is authenticated to continue or not.

        Should return either ``True`` if allowed, ``False`` if not or an
        ``HttpResponse`` if you need something custom.
        """
        return True

    def get_identifier(self, request):
        """
        Provides a unique string identifier for the requestor.

        This implementation returns a combination of IP address and hostname.
        """
        return "%s_%s" % (request.META.get('REMOTE_ADDR', 'noaddr'), request.META.get('REMOTE_HOST', 'nohost'))

    def check_credentials(self, **kwargs):
        """
        After the authentication mechanism has been verified, does any
        server-side check of the actual credentials, such as username/password.

        Should return either the object representing the user or raise ``Unauthorized``.
        """
        raise NotImplementedError("You must implement the 'check_credentials' method on your 'Authentication' class.")


class BasicAuthentication(Authentication):
    """
    Handles HTTP Basic auth against a specific auth backend if provided,
    or against all configured authentication backends using the
    ``authenticate`` method from ``django.contrib.auth``.

    Optional keyword arguments:

    ``backend``
        If specified, use a specific ``django.contrib.auth`` backend instead
        of checking all backends specified in the ``AUTHENTICATION_BACKENDS``
        setting.
    ``realm``
        The realm to use in the ``HttpUnauthorized`` response.  Default:
        ``django-tastypie``.
    """
    realm = 'piecrust'

    def __init__(self, backend=None, realm=None):
        self.backend = backend

        if realm is not None:
            self.realm = realm

    def _unauthorized(self):
        response = HttpUnauthorized()
        # FIXME: Sanitize realm.
        response['WWW-Authenticate'] = 'Basic Realm="%s"' % self.realm
        return response

    def is_authenticated(self, request, **kwargs):
        """
        Checks a user's basic auth credentials.

        Should return either ``True`` if allowed, ``False`` if not or an
        ``HttpResponse`` if you need something custom.
        """
        if not request.META.get('HTTP_AUTHORIZATION'):
            return self._unauthorized()

        try:
            (auth_type, data) = request.META['HTTP_AUTHORIZATION'].split()
            if auth_type != 'Basic':
                return self._unauthorized()
            user_pass = base64.b64decode(data)
        except:
            return self._unauthorized()

        bits = user_pass.split(':', 1)

        if len(bits) != 2:
            return self._unauthorized()

        try:
            user = self.check_credentials(username=bits[0], password=bits[1])
        except Unauthorized:
            return self._unauthorized()

        request.user = user
        return True

    def get_identifier(self, request):
        """
        Provides a unique string identifier for the requestor.

        This implementation returns the user's basic auth username.
        """
        return request.META.get('REMOTE_USER', 'nouser')


class ApiKeyAuthentication(Authentication):
    """
    Handles API key auth, in which a user provides a username & API key.

    Uses the ``ApiKey`` model that ships with tastypie. If you wish to use
    a different model, override the ``get_key`` method to perform the key check
    as suits your needs.
    """
    def _unauthorized(self):
        return HttpUnauthorized()

    def is_authenticated(self, request, **kwargs):
        """
        Finds the user and checks their API key.

        Should return either ``True`` if allowed, ``False`` if not or an
        ``HttpResponse`` if you need something custom.
        """
        username = request.GET.get('username') or request.POST.get('username')
        api_key = request.GET.get('api_key') or request.POST.get('api_key')

        if not username or not api_key:
            return self._unauthorized()

        try:
            user = self.check_credentials(username=username, api_key=api_key)
        except Unauthorized:
            return self._unauthorized()

        request.user = user
        return True

    def get_identifier(self, request):
        """
        Provides a unique string identifier for the requestor.

        This implementation returns the user's username.
        """
        return request.REQUEST.get('username', 'nouser')


class DigestAuthentication(Authentication):
    """
    Handles HTTP Digest auth against a specific auth backend if provided,
    or against all configured authentication backends using the
    ``authenticate`` method from ``django.contrib.auth``. However, instead of
    the user's password, their API key should be used.

    Optional keyword arguments:

    ``backend``
        If specified, use a specific ``django.contrib.auth`` backend instead
        of checking all backends specified in the ``AUTHENTICATION_BACKENDS``
        setting.
    ``realm``
        The realm to use in the ``HttpUnauthorized`` response.  Default:
        ``django-tastypie``.
    """
    secret_key = None
    realm = 'piecrust'

    def __init__(self, backend=None, realm=None, secret_key=None):
        self.backend = backend

        if realm is not None:
            self.realm = realm

        if python_digest is None:
            raise ImproperlyConfigured("The 'python_digest' package could not be imported. It is required for use with the 'DigestAuthentication' class.")

        if secret_key is None and self.secret_key is None:
            raise ImproperlyConfigured("The 'DigestAuthentication' class requires a secret key.")

    def _unauthorized(self):
        response = HttpUnauthorized()
        new_uuid = uuid.uuid4()
        opaque = hmac.new(str(new_uuid), digestmod=sha1).hexdigest()
        response['WWW-Authenticate'] = python_digest.build_digest_challenge(time.time(), self.secret_key, self.realm, opaque, False)
        return response

    def is_authenticated(self, request, **kwargs):
        """
        Finds the user and checks their API key.

        Should return either ``True`` if allowed, ``False`` if not or an
        ``HttpResponse`` if you need something custom.
        """
        if not request.META.get('HTTP_AUTHORIZATION'):
            return self._unauthorized()

        try:
            (auth_type, data) = request.META['HTTP_AUTHORIZATION'].split(' ', 1)

            if auth_type != 'Digest':
                return self._unauthorized()
        except:
            return self._unauthorized()

        digest_response = python_digest.parse_digest_credentials(request.META['HTTP_AUTHORIZATION'])

        if not python_digest.validate_nonce(digest_response.nonce, self.secret_key):
            return self._unauthorized()

        try:
            user = self.check_credentials(request=request, digest_response=digest_response.response, username=digest_response.username)
        except Unauthorized:
            return self._unauthorized()

        request.user = user
        return True

    def calculate_request_digest(self, request, digest_response, username, api_key):
        return python_digest.calculate_request_digest(
            request.method,
            python_digest.calculate_partial_digest(username, self.realm, api_key),
            digest_response)

    def get_identifier(self, request):
        """
        Provides a unique string identifier for the requestor.

        This implementation returns the user's username.
        """
        if hasattr(request, 'user'):
            if hasattr(request.user, 'username'):
                return request.user.username

        return 'nouser'

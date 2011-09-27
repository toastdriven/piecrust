import warnings
from piecrust.exceptions import ImproperlyConfigured, NotRegistered, BadRequest
from piecrust.http import ResponseGenerator, HttpOK
from piecrust.serializers import Serializer
from piecrust.utils import is_valid_jsonp_callback_value
from piecrust.utils.mime import determine_format, build_content_type


class Api(object):
    """
    Implements a registry to tie together the various resources that make up
    an API.

    Especially useful for navigation, HATEOAS and for providing multiple
    versions of your API.

    Optionally supplying ``api_name`` allows you to name the API. Generally,
    this is done with version numbers (i.e. ``v1``, ``v2``, etc.) but can
    be named any string.
    """
    serializer = Serializer()
    response_generator = ResponseGenerator()

    def __init__(self, api_name="v1", serializer=None, response_generator=None):
        self.api_name = api_name
        self._registry = {}
        self._canonicals = {}

        if serializer:
            self.serializer = serializer

        if response_generator:
            self.response_generator = response_generator

    def register(self, resource, canonical=True):
        """
        Registers an instance of a ``Resource`` subclass with the API.

        Optionally accept a ``canonical`` argument, which indicates that the
        resource being registered is the canonical variant. Defaults to
        ``True``.
        """
        resource_name = getattr(resource._meta, 'resource_name', None)

        if resource_name is None:
            raise ImproperlyConfigured("Resource %r must define a 'resource_name'." % resource)

        self._registry[resource_name] = resource

        if canonical is True:
            if resource_name in self._canonicals:
                warnings.warn("A new resource '%r' is replacing the existing canonical URL for '%s'." % (resource, resource_name), Warning, stacklevel=2)

            self._canonicals[resource_name] = resource
            # TODO: This is messy, but makes URI resolution on FK/M2M fields
            #       work consistently.
            resource._meta.api_name = self.api_name
            resource.__class__.Meta.api_name = self.api_name

    def unregister(self, resource_name):
        """
        If present, unregisters a resource from the API.
        """
        if resource_name in self._registry:
            del(self._registry[resource_name])

        if resource_name in self._canonicals:
            del(self._canonicals[resource_name])

    def canonical_resource_for(self, resource_name):
        """
        Returns the canonical resource for a given ``resource_name``.
        """
        if resource_name in self._canonicals:
            return self._canonicals[resource_name]

        raise NotRegistered("No resource was registered as canonical for '%s'." % resource_name)

    def wrap_view(self, view):
        def wrapper(request, *args, **kwargs):
            return getattr(self, view)(request, *args, **kwargs)
        return wrapper

    def override_urls(self):
        """
        A hook for adding your own URLs or overriding the default URLs.
        """
        return []

    @property
    def urls(self):
        """
        Provides URLconf details for the ``Api`` and all registered
        ``Resources`` beneath it.
        """
        raise NotImplementedError("You'll need to subclass 'Api' to provide a URL setup.")

    def top_level(self, request, api_name=None):
        """
        A view that returns a serialized list of all resources registers
        to the ``Api``. Useful for discovery.
        """
        available_resources = {}

        if api_name is None:
            api_name = self.api_name

        for name in sorted(self._registry.keys()):
            available_resources[name] = {
                'list_endpoint': self._build_reverse_url("api_dispatch_list", kwargs={
                    'api_name': api_name,
                    'resource_name': name,
                }),
                'schema': self._build_reverse_url("api_get_schema", kwargs={
                    'api_name': api_name,
                    'resource_name': name,
                }),
            }

        desired_format = determine_format(request, self.serializer)
        options = {}

        if 'text/javascript' in desired_format:
            callback = request.GET.get('callback', 'callback')

            if not is_valid_jsonp_callback_value(callback):
                raise BadRequest('JSONP callback name is invalid.')

            options['callback'] = callback

        serialized = self.serializer.serialize(available_resources, desired_format, options)
        return self.response_generator.create(HttpOK(content=serialized, content_type=build_content_type(desired_format)))

    def _build_reverse_url(self, name, args=None, kwargs=None):
        """
        A convenience hook for overriding how URLs are built.
        """
        raise NotImplementedError("You must subclass 'Api' to provide a way to \"reverse\" a URL.")

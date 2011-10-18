from copy import deepcopy
# from django.conf.urls.defaults import patterns, url
# from django.core.urlresolvers import NoReverseMatch, reverse, resolve, Resolver404, get_script_prefix
# from django.http import HttpResponse, HttpResponseNotFound
from piecrust.authentication import Authentication
from piecrust.authorization import ReadOnlyAuthorization
from piecrust.bundle import Bundle
from piecrust.cache import NoCache
from piecrust.exceptions import NotFound, BadRequest, HydrationError, ImmediateHttpResponse, ObjectDoesNotExist, MultipleObjectsReturned, ValidationError
from piecrust import fields
from piecrust import http
from piecrust.paginator import Paginator
from piecrust.serializers import Serializer
from piecrust.storage import BaseStorage
from piecrust.throttle import BaseThrottle
from piecrust.uris import UriHandler
from piecrust.utils import is_valid_jsonp_callback_value, dict_strip_unicode_keys, trailing_slash
from piecrust.utils.mime import determine_format, build_content_type
from piecrust.validation import Validation
# If ``csrf_exempt`` isn't present, stub it.
try:
    from django.views.decorators.csrf import csrf_exempt
except ImportError:
    def csrf_exempt(func):
        return func
try:
    from django.utils.cache import patch_cache_control
except ImportError:
    def patch_cache_control(*args, **kwargs):
        # TODO: This hurts in the case of IE. The only choice is to copy-paste
        #       from Django or ignore. For now, ignore.
        pass


class ResourceOptions(object):
    """
    A configuration class for ``Resource``.

    Provides sane defaults and the logic needed to augment these settings with
    the internal ``class Meta`` used on ``Resource`` subclasses.
    """
    storage = BaseStorage()
    serializer = Serializer()
    authentication = Authentication()
    authorization = ReadOnlyAuthorization()
    cache = NoCache()
    throttle = BaseThrottle()
    validation = Validation()
    paginator_class = Paginator
    uri_handler = UriHandler()
    allowed_methods = ['get', 'post', 'put', 'delete', 'patch']
    list_allowed_methods = None
    detail_allowed_methods = None
    limit = 20
    api_name = None
    resource_name = None
    urlconf_namespace = None
    default_format = 'application/json'
    filtering = {}
    ordering = []
    object_class = None
    queryset = None
    fields = []
    excludes = []
    include_resource_uri = True
    include_absolute_url = False
    always_return_data = False

    def __new__(cls, meta=None):
        overrides = {}

        # Handle overrides.
        if meta:
            for override_name in dir(meta):
                # No internals please.
                if not override_name.startswith('_'):
                    overrides[override_name] = getattr(meta, override_name)

        allowed_methods = overrides.get('allowed_methods', ['get', 'post', 'put', 'delete', 'patch'])

        if overrides.get('list_allowed_methods', None) is None:
            overrides['list_allowed_methods'] = allowed_methods

        if overrides.get('detail_allowed_methods', None) is None:
            overrides['detail_allowed_methods'] = allowed_methods

        return object.__new__(type('ResourceOptions', (cls,), overrides))


class DeclarativeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        attrs['base_fields'] = {}
        declared_fields = {}

        # Inherit any fields from parent(s).
        try:
            parents = [b for b in bases if issubclass(b, Resource)]
            # Simulate the MRO.
            parents.reverse()

            for p in parents:
                parent_fields = getattr(p, 'base_fields', {})

                for field_name, field_object in parent_fields.items():
                    attrs['base_fields'][field_name] = deepcopy(field_object)
        except NameError:
            pass

        for field_name, obj in attrs.items():
            # Look for ``dehydrated_type`` instead of doing ``isinstance``,
            # which can break down if Tastypie is re-namespaced as something
            # else.
            if hasattr(obj, 'dehydrated_type'):
                field = attrs.pop(field_name)
                declared_fields[field_name] = field

        attrs['base_fields'].update(declared_fields)
        attrs['declared_fields'] = declared_fields
        new_class = super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ResourceOptions(opts)

        if not getattr(new_class._meta, 'resource_name', None):
            # No ``resource_name`` provided. Attempt to auto-name the resource.
            class_name = new_class.__name__
            name_bits = [bit for bit in class_name.split('Resource') if bit]
            resource_name = ''.join(name_bits).lower()
            new_class._meta.resource_name = resource_name

        if getattr(new_class._meta, 'include_resource_uri', True):
            if not 'resource_uri' in new_class.base_fields:
                new_class.base_fields['resource_uri'] = fields.CharField(readonly=True)
        elif 'resource_uri' in new_class.base_fields and not 'resource_uri' in attrs:
            del(new_class.base_fields['resource_uri'])

        for field_name, field_object in new_class.base_fields.items():
            if hasattr(field_object, 'contribute_to_class'):
                field_object.contribute_to_class(new_class, field_name)

        return new_class


class Resource(object):
    """
    Handles the data, request dispatch and responding to requests.

    Serialization/deserialization is handled "at the edges" (i.e. at the
    beginning/end of the request/response cycle) so that everything internally
    is Python data structures.

    This class tries to be non-model specific, so it can be hooked up to other
    data sources, such as search results, files, other data, etc.
    """
    __metaclass__ = DeclarativeMetaclass

    def __init__(self, api_name=None):
        self.fields = deepcopy(self.base_fields)

        if not api_name is None:
            self._meta.api_name = api_name

    def __getattr__(self, name):
        if name in self.fields:
            return self.fields[name]
        raise AttributeError(name)

    def wrap_view(self, view):
        """
        Wraps methods so they can be called in a more functional way as well
        as handling exceptions better.

        Note that if ``BadRequest`` or an exception with a ``response`` attr
        are seen, there is special handling to either present a message back
        to the user or return the response traveling with the exception.
        """
        @csrf_exempt
        def wrapper(request, *args, **kwargs):
            try:
                callback = getattr(self, view)
                response = callback(request, *args, **kwargs)

                if request.is_ajax():
                    # IE excessively caches XMLHttpRequests, so we're disabling
                    # the browser cache here.
                    # See http://www.enhanceie.com/ie/bugs.asp for details.
                    patch_cache_control(response, no_cache=True)

                return response
            except (BadRequest, fields.ApiFieldError, ValidationError), e:
                return self.bad_request(request, e)
            except Exception, e:
                return self.handle_500(request, e)

        return wrapper

    def bad_request(self, request, exception):
        data = {
            "error_message": unicode(exception),
        }

        if self._meta.include_traceback:
            import traceback
            import sys
            the_trace = '\n'.join(traceback.format_exception(*(sys.exc_info())))
            data["traceback"] = the_trace

        try:
            return self.create_response(request, data, response_class=http.HttpBadRequest)
        except:
            return http.HttpBadRequest()

    def handle_500(self, request, exception):
        if hasattr(exception, 'response'):
            return exception.response

        # A real, non-expected exception.
        # Handle the case where the full traceback is more helpful
        # than the serialized error.
        if getattr(self._meta, 'debug', False):
            raise

        # Rather than re-raising, we're going to things similar to
        # what Django does. The difference is returning a serialized
        # error message.
        import traceback
        import sys
        the_trace = '\n'.join(traceback.format_exception(*(sys.exc_info())))
        response_class = http.HttpApplicationError

        if isinstance(exception, (NotFound, ObjectDoesNotExist)):
            response_class = http.HttpNotFound

        data = {
            "error_message": unicode(exception),
            "traceback": the_trace,
        }
        return self.create_response(request, data, response_class=response_class)

    def _build_reverse_url(self, name, args=None, kwargs=None):
        """
        A convenience hook for overriding how URLs are built.

        See ``NamespacedModelResource._build_reverse_url`` for an example.
        """
        return reverse(name, args=args, kwargs=kwargs)

    def base_urls(self):
        """
        The standard URLs this ``Resource`` should respond to.
        """
        # Due to the way Django parses URLs, ``get_multiple`` won't work without
        # a trailing slash.
        return [
            url(r"^(?P<resource_name>%s)%s$" % (self._meta.resource_name, trailing_slash()), self.wrap_view('dispatch_list'), name="api_dispatch_list"),
            url(r"^(?P<resource_name>%s)/schema%s$" % (self._meta.resource_name, trailing_slash()), self.wrap_view('get_schema'), name="api_get_schema"),
            url(r"^(?P<resource_name>%s)/set/(?P<pk_list>\w[\w/;-]*)/$" % self._meta.resource_name, self.wrap_view('get_multiple'), name="api_get_multiple"),
            url(r"^(?P<resource_name>%s)/(?P<pk>\w[\w/-]*)%s$" % (self._meta.resource_name, trailing_slash()), self.wrap_view('dispatch_detail'), name="api_dispatch_detail"),
        ]

    def override_urls(self):
        """
        A hook for adding your own URLs or overriding the default URLs.
        """
        return []

    @property
    def urls(self):
        """
        The endpoints this ``Resource`` responds to.

        Mostly a standard URLconf, this is suitable for either automatic use
        when registered with an ``Api`` class or for including directly in
        a URLconf should you choose to.
        """
        urls = self.override_urls() + self.base_urls()
        urlpatterns = patterns('',
            *urls
        )
        return urlpatterns

    def create_response(self, request, data, response_class=HttpResponse, **response_kwargs):
        """
        Extracts the common "which-format/serialize/return-response" cycle.

        Mostly a useful shortcut/hook.
        """
        desired_format = self.determine_format(request)
        serialized = self.serialize(request, data, desired_format)
        return response_class(content=serialized, content_type=build_content_type(desired_format), **response_kwargs)

    def determine_format(self, request):
        """
        Used to determine the desired format.

        Largely relies on ``tastypie.utils.mime.determine_format`` but here
        as a point of extension.
        """
        return determine_format(request, self._meta.serializer, default_format=self._meta.default_format)

    def serialize(self, request, data, format, options=None):
        """
        Given a request, data and a desired format, produces a serialized
        version suitable for transfer over the wire.

        Mostly a hook, this uses the ``Serializer`` from ``Resource._meta``.
        """
        options = options or {}

        if 'text/javascript' in format:
            # get JSONP callback name. default to "callback"
            callback = request.GET.get('callback', 'callback')

            if not is_valid_jsonp_callback_value(callback):
                raise BadRequest('JSONP callback name is invalid.')

            options['callback'] = callback

        return self._meta.serializer.serialize(data, format, options)

    def deserialize(self, request, data, format='application/json'):
        """
        Given a request, data and a format, deserializes the given data.

        It relies on the request properly sending a ``CONTENT_TYPE`` header,
        falling back to ``application/json`` if not provided.

        Mostly a hook, this uses the ``Serializer`` from ``Resource._meta``.
        """
        deserialized = self._meta.serializer.deserialize(data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        return deserialized

    def alter_list_data_to_serialize(self, request, data):
        """
        A hook to alter list data just before it gets serialized & sent to the user.

        Useful for restructuring/renaming aspects of the what's going to be
        sent.

        Should accommodate for a list of objects, generally also including
        meta data.
        """
        return data

    def alter_detail_data_to_serialize(self, request, data):
        """
        A hook to alter detail data just before it gets serialized & sent to the user.

        Useful for restructuring/renaming aspects of the what's going to be
        sent.

        Should accommodate for receiving a single bundle of data.
        """
        return data

    def alter_deserialized_list_data(self, request, data):
        """
        A hook to alter list data just after it has been received from the user &
        gets deserialized.

        Useful for altering the user data before any hydration is applied.
        """
        return data

    def alter_deserialized_detail_data(self, request, data):
        """
        A hook to alter detail data just after it has been received from the user &
        gets deserialized.

        Useful for altering the user data before any hydration is applied.
        """
        return data

    def dispatch_list(self, request, **kwargs):
        """
        A view for handling the various HTTP methods (GET/POST/PUT/DELETE) over
        the entire list of resources.

        Relies on ``Resource.dispatch`` for the heavy-lifting.
        """
        return self.dispatch('list', request, **kwargs)

    def dispatch_detail(self, request, **kwargs):
        """
        A view for handling the various HTTP methods (GET/POST/PUT/DELETE) on
        a single resource.

        Relies on ``Resource.dispatch`` for the heavy-lifting.
        """
        return self.dispatch('detail', request, **kwargs)

    def dispatch(self, request_type, request, **kwargs):
        """
        Handles the common operations (allowed HTTP method, authentication,
        throttling, method lookup) surrounding most CRUD interactions.
        """
        allowed_methods = getattr(self._meta, "%s_allowed_methods" % request_type, None)
        request_method = self.method_check(request, allowed=allowed_methods)

        method = getattr(self, "%s_%s" % (request_method, request_type), None)

        if method is None:
            raise ImmediateHttpResponse(response=http.HttpNotImplemented())

        self.is_authenticated(request)
        self.is_authorized(request)
        self.throttle_check(request)

        # All clear. Process the request.
        request = self.convert_post_to_put(request)
        response = method(request, **kwargs)

        # Add the throttled request.
        self.log_throttled_access(request)

        # If what comes back isn't a ``HttpResponse``, assume that the
        # request was accepted and that some action occurred. This also
        # prevents Django from freaking out.
        if not isinstance(response, HttpResponse):
            return http.HttpNoContent()

        return response

    def remove_api_resource_names(self, url_dict):
        """
        Given a dictionary of regex matches from a URLconf, removes
        ``api_name`` and/or ``resource_name`` if found.

        This is useful for converting URLconf matches into something suitable
        for data lookup. For example::

            Model.objects.filter(**self.remove_api_resource_names(matches))
        """
        kwargs_subset = url_dict.copy()

        for key in ['api_name', 'resource_name']:
            try:
                del(kwargs_subset[key])
            except KeyError:
                pass

        return kwargs_subset

    def method_check(self, request, allowed=None):
        """
        Ensures that the HTTP method used on the request is allowed to be
        handled by the resource.

        Takes an ``allowed`` parameter, which should be a list of lowercase
        HTTP methods to check against. Usually, this looks like::

            # The most generic lookup.
            self.method_check(request, self._meta.allowed_methods)

            # A lookup against what's allowed for list-type methods.
            self.method_check(request, self._meta.list_allowed_methods)

            # A useful check when creating a new endpoint that only handles
            # GET.
            self.method_check(request, ['get'])
        """
        if allowed is None:
            allowed = []

        request_method = request.method.lower()

        if request_method == "options":
            allows = ','.join(map(str.upper, allowed))
            response = HttpResponse(allows)
            response['Allow'] = allows
            raise ImmediateHttpResponse(response=response)

        if not request_method in allowed:
            raise ImmediateHttpResponse(response=http.HttpMethodNotAllowed())

        return request_method

    def is_authorized(self, request, object=None):
        """
        Handles checking of permissions to see if the user has authorization
        to GET, POST, PUT, or DELETE this resource.  If ``object`` is provided,
        the authorization backend can apply additional row-level permissions
        checking.
        """
        auth_result = self._meta.authorization.is_authorized(request, object)

        if isinstance(auth_result, HttpResponse):
            raise ImmediateHttpResponse(response=auth_result)

        if not auth_result is True:
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

    def is_authenticated(self, request):
        """
        Handles checking if the user is authenticated and dealing with
        unauthenticated users.

        Mostly a hook, this uses class assigned to ``authentication`` from
        ``Resource._meta``.
        """
        # Authenticate the request as needed.
        auth_result = self._meta.authentication.is_authenticated(request)

        if isinstance(auth_result, HttpResponse):
            raise ImmediateHttpResponse(response=auth_result)

        if not auth_result is True:
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

    def throttle_check(self, request):
        """
        Handles checking if the user should be throttled.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        identifier = self._meta.authentication.get_identifier(request)

        # Check to see if they should be throttled.
        if self._meta.throttle.should_be_throttled(identifier):
            # Throttle limit exceeded.
            raise ImmediateHttpResponse(response=http.HttpForbidden())

    def log_throttled_access(self, request):
        """
        Handles the recording of the user's access for throttling purposes.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        request_method = request.method.lower()
        self._meta.throttle.accessed(self._meta.authentication.get_identifier(request), url=request.get_full_path(), request_method=request_method)

    def build_bundle(self, obj=None, data=None, request=None):
        """
        Given either an object, a data dictionary or both, builds a ``Bundle``
        for use throughout the ``dehydrate/hydrate`` cycle.

        If no object is provided, an empty object from
        ``Resource._meta.object_class`` is created so that attempts to access
        ``bundle.obj`` do not fail.
        """
        if obj is None:
            obj = self._meta.object_class()

        return Bundle(obj=obj, data=data, request=request)

    def build_filters(self, filters=None):
        """
        Allows for the filtering of applicable objects.

        This needs to be implemented at the user level.'

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        return filters

    def apply_sorting(self, obj_list, options=None):
        """
        Allows for the sorting of objects being returned.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        return obj_list

    # URL-related methods.

    def get_resource_uri(self, bundle_or_obj):
        """
        This needs to be implemented at the user level.

        A ``return reverse("api_dispatch_detail", kwargs={'resource_name':
        self.resource_name, 'pk': object.id})`` should be all that would
        be needed.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def get_resource_list_uri(self):
        """
        Returns a URL specific to this resource's list endpoint.
        """
        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        try:
            return self._build_reverse_url("api_dispatch_list", kwargs=kwargs)
        except NoReverseMatch:
            return None

    def get_via_uri(self, uri, request=None):
        """
        This pulls apart the salient bits of the URI and populates the
        resource via a ``obj_get``.

        Optionally accepts a ``request``.

        If you need custom behavior based on other portions of the URI,
        simply override this method.
        """
        prefix = get_script_prefix()
        chomped_uri = uri

        if prefix and chomped_uri.startswith(prefix):
            chomped_uri = chomped_uri[len(prefix)-1:]

        try:
            view, args, kwargs = resolve(chomped_uri)
        except Resolver404:
            raise NotFound("The URL provided '%s' was not a link to a valid resource." % uri)

        return self.obj_get(request=request, **self.remove_api_resource_names(kwargs))

    # Data preparation.

    def full_dehydrate(self, bundle):
        """
        Given a bundle with an object instance, extract the information from it
        to populate the resource.
        """
        # Dehydrate each field.
        for field_name, field_object in self.fields.items():
            # A touch leaky but it makes URI resolution work.
            if getattr(field_object, 'dehydrated_type', None) == 'related':
                field_object.api_name = self._meta.api_name
                field_object.resource_name = self._meta.resource_name

            bundle.data[field_name] = field_object.dehydrate(bundle)

            # Check for an optional method to do further dehydration.
            method = getattr(self, "dehydrate_%s" % field_name, None)

            if method:
                bundle.data[field_name] = method(bundle)

        bundle = self.dehydrate(bundle)
        return bundle

    def dehydrate(self, bundle):
        """
        A hook to allow a final manipulation of data once all fields/methods
        have built out the dehydrated data.

        Useful if you need to access more than one dehydrated field or want
        to annotate on additional data.

        Must return the modified bundle.
        """
        return bundle

    def full_hydrate(self, bundle):
        """
        Given a populated bundle, distill it and turn it back into
        a full-fledged object instance.
        """
        if bundle.obj is None:
            bundle.obj = self._meta.object_class()

        bundle = self.hydrate(bundle)

        for field_name, field_object in self.fields.items():
            if field_object.readonly is True:
                continue

            # Check for an optional method to do further hydration.
            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                bundle = method(bundle)

            if field_object.attribute:
                value = field_object.hydrate(bundle)

                if value is not None or field_object.null:
                    # We need to avoid populating M2M data here as that will
                    # cause things to blow up.
                    if not getattr(field_object, 'is_related', False):
                        setattr(bundle.obj, field_object.attribute, value)
                    elif not getattr(field_object, 'is_m2m', False):
                        if value is not None:
                            setattr(bundle.obj, field_object.attribute, value.obj)
                        elif field_object.blank:
                            continue
                        elif field_object.null:
                            setattr(bundle.obj, field_object.attribute, value)

        return bundle

    def hydrate(self, bundle):
        """
        A hook to allow a final manipulation of data once all fields/methods
        have built out the hydrated data.

        Useful if you need to access more than one hydrated field or want
        to annotate on additional data.

        Must return the modified bundle.
        """
        return bundle

    def hydrate_m2m(self, bundle):
        """
        Populate the ManyToMany data on the instance.
        """
        if bundle.obj is None:
            raise HydrationError("You must call 'full_hydrate' before attempting to run 'hydrate_m2m' on %r." % self)

        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_m2m', False):
                continue

            if field_object.attribute:
                # Note that we only hydrate the data, leaving the instance
                # unmodified. It's up to the user's code to handle this.
                # The ``ModelResource`` provides a working baseline
                # in this regard.
                bundle.data[field_name] = field_object.hydrate_m2m(bundle)

        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_m2m', False):
                continue

            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                method(bundle)

        return bundle

    def build_schema(self):
        """
        Returns a dictionary of all the fields on the resource and some
        properties about those fields.

        Used by the ``schema/`` endpoint to describe what will be available.
        """
        data = {
            'fields': {},
            'default_format': self._meta.default_format,
            'allowed_list_http_methods': self._meta.list_allowed_methods,
            'allowed_detail_http_methods': self._meta.detail_allowed_methods,
            'default_limit': self._meta.limit,
        }

        if self._meta.ordering:
            data['ordering'] = self._meta.ordering

        if self._meta.filtering:
            data['filtering'] = self._meta.filtering

        for field_name, field_object in self.fields.items():
            data['fields'][field_name] = {
                'default': field_object.default,
                'type': field_object.dehydrated_type,
                'nullable': field_object.null,
                'blank': field_object.blank,
                'readonly': field_object.readonly,
                'help_text': field_object.help_text,
                'unique': field_object.unique,
            }

        return data

    def dehydrate_resource_uri(self, bundle):
        """
        For the automatically included ``resource_uri`` field, dehydrate
        the URI for the given bundle.

        Returns empty string if no URI can be generated.
        """
        try:
            return self.get_resource_uri(bundle)
        except NotImplementedError:
            return ''
        except NoReverseMatch:
            return ''

    def generate_cache_key(self, *args, **kwargs):
        """
        Creates a unique-enough cache key.

        This is based off the current api_name/resource_name/args/kwargs.
        """
        smooshed = []

        for key, value in kwargs.items():
            smooshed.append("%s=%s" % (key, value))

        # Use a list plus a ``.join()`` because it's faster than concatenation.
        return "%s:%s:%s:%s" % (self._meta.api_name, self._meta.resource_name, ':'.join(args), ':'.join(smooshed))

    # Data access methods.

    def get_object_list(self, request):
        """
        A hook to allow making returning the list of available objects.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def apply_authorization_limits(self, request, object_list):
        """
        Allows the ``Authorization`` class to further limit the object list.
        Also a hook to customize per ``Resource``.
        """
        if hasattr(self._meta.authorization, 'apply_limits'):
            object_list = self._meta.authorization.apply_limits(request, object_list)

        return object_list

    def can_create(self):
        """
        Checks to ensure ``post`` is within ``allowed_methods``.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'post' in allowed

    def can_update(self):
        """
        Checks to ensure ``put`` is within ``allowed_methods``.

        Used when hydrating related data.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'put' in allowed

    def can_delete(self):
        """
        Checks to ensure ``delete`` is within ``allowed_methods``.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'delete' in allowed

    def apply_filters(self, request, applicable_filters):
        """
        A hook to alter how the filters are applied to the object list.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_get_list(self, request=None, **kwargs):
        """
        Fetches the list of objects available on the resource.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def cached_obj_get_list(self, request=None, **kwargs):
        """
        A version of ``obj_get_list`` that uses the cache as a means to get
        commonly-accessed data faster.
        """
        cache_key = self.generate_cache_key('list', **kwargs)
        obj_list = self._meta.cache.get(cache_key)

        if obj_list is None:
            obj_list = self.obj_get_list(request=request, **kwargs)
            self._meta.cache.set(cache_key, obj_list)

        return obj_list

    def obj_get(self, request=None, **kwargs):
        """
        Fetches an individual object on the resource.

        This needs to be implemented at the user level. If the object can not
        be found, this should raise a ``NotFound`` exception.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def cached_obj_get(self, request=None, **kwargs):
        """
        A version of ``obj_get`` that uses the cache as a means to get
        commonly-accessed data faster.
        """
        cache_key = self.generate_cache_key('detail', **kwargs)
        bundle = self._meta.cache.get(cache_key)

        if bundle is None:
            bundle = self.obj_get(request=request, **kwargs)
            self._meta.cache.set(cache_key, bundle)

        return bundle

    def obj_create(self, bundle, request=None, **kwargs):
        """
        Creates a new object based on the provided data.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_update(self, bundle, request=None, **kwargs):
        """
        Updates an existing object (or creates a new object) based on the
        provided data.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_delete_list(self, request=None, **kwargs):
        """
        Deletes an entire list of objects.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_delete(self, request=None, **kwargs):
        """
        Deletes a single object.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def is_valid(self, bundle, request=None):
        """
        Handles checking if the data provided by the user is valid.

        Mostly a hook, this uses class assigned to ``validation`` from
        ``Resource._meta``.

        If validation fails, an error is raised with the error messages
        serialized inside it.
        """
        errors = self._meta.validation.is_valid(bundle, request)

        if len(errors):
            if request:
                desired_format = self.determine_format(request)
            else:
                desired_format = self._meta.default_format

            serialized = self.serialize(request, errors, desired_format)
            response = http.HttpBadRequest(content=serialized, content_type=build_content_type(desired_format))
            raise ImmediateHttpResponse(response=response)

    def rollback(self, bundles):
        """
        Given the list of bundles, delete all objects pertaining to those
        bundles.

        This needs to be implemented at the user level. No exceptions should
        be raised if possible.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def convert_post_to_VERB(self, request, verb):
        """
        Force Django to process the VERB.
        """
        # Based off of ``piston.utils.coerce_put_post``. Similarly BSD-licensed.
        # And no, the irony is not lost on me.
        if request.method == verb:
            if hasattr(request, '_post'):
                del(request._post)
                del(request._files)

            try:
                request.method = "POST"
                request._load_post_and_files()
                request.method = verb
            except AttributeError:
                request.META['REQUEST_METHOD'] = 'POST'
                request._load_post_and_files()
                request.META['REQUEST_METHOD'] = verb

            setattr(request, verb, request.POST)

        return request

    def convert_post_to_put(self, request):
        return self.convert_post_to_VERB(request, verb='PUT')

    def convert_post_to_patch(self, request):
        return self.convert_post_to_VERB(request, verb='PATCH')

    # Views.

    def get_list(self, request, **kwargs):
        """
        Returns a serialized list of resources.

        Calls ``obj_get_list`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        # TODO: Uncached for now. Invalidation that works for everyone may be
        #       impossible.
        objects = self.obj_get_list(request=request, **self.remove_api_resource_names(kwargs))
        sorted_objects = self.apply_sorting(objects, options=request.GET)

        paginator = self._meta.paginator_class(request.GET, sorted_objects, resource_uri=self.get_resource_list_uri(), limit=self._meta.limit)
        to_be_serialized = paginator.page()

        # Dehydrate the bundles in preparation for serialization.
        bundles = [self.build_bundle(obj=obj, request=request) for obj in to_be_serialized['objects']]
        to_be_serialized['objects'] = [self.full_dehydrate(bundle) for bundle in bundles]
        to_be_serialized = self.alter_list_data_to_serialize(request, to_be_serialized)
        return self.create_response(request, to_be_serialized)

    def get_detail(self, request, **kwargs):
        """
        Returns a single serialized resource.

        Calls ``cached_obj_get/obj_get`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        try:
            obj = self.cached_obj_get(request=request, **self.remove_api_resource_names(kwargs))
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one resource is found at this URI.")

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)
        return self.create_response(request, bundle)

    def put_list(self, request, **kwargs):
        """
        Replaces a collection of resources with another collection.

        Calls ``delete_list`` to clear out the collection then ``obj_create``
        with the provided the data to create the new collection.

        Return ``HttpNoContent`` (204 No Content) if
        ``Meta.always_return_data = False`` (default).

        Return ``HttpAccepted`` (202 Accepted) if
        ``Meta.always_return_data = True``.
        """
        deserialized = self.deserialize(request, request.raw_post_data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_list_data(request, deserialized)

        if not 'objects' in deserialized:
            raise BadRequest("Invalid data sent.")

        self.obj_delete_list(request=request, **self.remove_api_resource_names(kwargs))
        bundles_seen = []

        for object_data in deserialized['objects']:
            bundle = self.build_bundle(data=dict_strip_unicode_keys(object_data), request=request)

            # Attempt to be transactional, deleting any previously created
            # objects if validation fails.
            try:
                self.is_valid(bundle, request)
            except ImmediateHttpResponse:
                self.rollback(bundles_seen)
                raise

            self.obj_create(bundle, request=request, **self.remove_api_resource_names(kwargs))
            bundles_seen.append(bundle)

        if not self._meta.always_return_data:
            return http.HttpNoContent()
        else:
            to_be_serialized = {}
            to_be_serialized['objects'] = [self.full_dehydrate(bundle) for bundle in bundles_seen]
            to_be_serialized = self.alter_list_data_to_serialize(request, to_be_serialized)
            return self.create_response(request, to_be_serialized, response_class=http.HttpAccepted)

    def put_detail(self, request, **kwargs):
        """
        Either updates an existing resource or creates a new one with the
        provided data.

        Calls ``obj_update`` with the provided data first, but falls back to
        ``obj_create`` if the object does not already exist.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        If ``Meta.always_return_data = True``, there will be a populated body
        of serialized data.

        If an existing resource is modified and
        ``Meta.always_return_data = False`` (default), return ``HttpNoContent``
        (204 No Content).
        If an existing resource is modified and
        ``Meta.always_return_data = True``, return ``HttpAccepted`` (202
        Accepted).
        """
        deserialized = self.deserialize(request, request.raw_post_data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_detail_data(request, deserialized)
        bundle = self.build_bundle(data=dict_strip_unicode_keys(deserialized), request=request)
        self.is_valid(bundle, request)

        try:
            updated_bundle = self.obj_update(bundle, request=request, **self.remove_api_resource_names(kwargs))

            if not self._meta.always_return_data:
                return http.HttpNoContent()
            else:
                updated_bundle = self.full_dehydrate(updated_bundle)
                updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
                return self.create_response(request, updated_bundle, response_class=http.HttpAccepted)
        except (NotFound, MultipleObjectsReturned):
            updated_bundle = self.obj_create(bundle, request=request, **self.remove_api_resource_names(kwargs))
            location = self.get_resource_uri(updated_bundle)

            if not self._meta.always_return_data:
                return http.HttpCreated(location=location)
            else:
                updated_bundle = self.full_dehydrate(updated_bundle)
                updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
                return self.create_response(request, updated_bundle, response_class=http.HttpCreated, location=location)

    def post_list(self, request, **kwargs):
        """
        Creates a new resource/object with the provided data.

        Calls ``obj_create`` with the provided data and returns a response
        with the new resource's location.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        If ``Meta.always_return_data = True``, there will be a populated body
        of serialized data.
        """
        deserialized = self.deserialize(request, request.raw_post_data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_detail_data(request, deserialized)
        bundle = self.build_bundle(data=dict_strip_unicode_keys(deserialized), request=request)
        self.is_valid(bundle, request)
        updated_bundle = self.obj_create(bundle, request=request, **self.remove_api_resource_names(kwargs))
        location = self.get_resource_uri(updated_bundle)

        if not self._meta.always_return_data:
            return http.HttpCreated(location=location)
        else:
            updated_bundle = self.full_dehydrate(updated_bundle)
            updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
            return self.create_response(request, updated_bundle, response_class=http.HttpCreated, location=location)

    def post_detail(self, request, **kwargs):
        """
        Creates a new subcollection of the resource under a resource.

        This is not implemented by default because most people's data models
        aren't self-referential.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        """
        return http.HttpNotImplemented()

    def delete_list(self, request, **kwargs):
        """
        Destroys a collection of resources/objects.

        Calls ``obj_delete_list``.

        If the resources are deleted, return ``HttpNoContent`` (204 No Content).
        """
        self.obj_delete_list(request=request, **self.remove_api_resource_names(kwargs))
        return http.HttpNoContent()

    def delete_detail(self, request, **kwargs):
        """
        Destroys a single resource/object.

        Calls ``obj_delete``.

        If the resource is deleted, return ``HttpNoContent`` (204 No Content).
        If the resource did not exist, return ``Http404`` (404 Not Found).
        """
        try:
            self.obj_delete(request=request, **self.remove_api_resource_names(kwargs))
            return http.HttpNoContent()
        except NotFound:
            return http.HttpNotFound()

    def patch_list(self, request, **kwargs):
        """
        Updates a collection in-place.

        The exact behavior of ``PATCH`` to a list resource is still the matter of
        some debate in REST circles, and the ``PATCH`` RFC isn't standard. So the
        behavior this method implements (described below) is something of a
        stab in the dark. It's mostly cribbed from GData, with a smattering
        of ActiveResource-isms and maybe even an original idea or two.

        The ``PATCH`` format is one that's similar to the response returned from
        a ``GET`` on a list resource::

            {
              "objects": [{object}, {object}, ...],
              "deleted_objects": ["URI", "URI", "URI", ...],
            }

        For each object in ``objects``:

            * If the dict does not have a ``resource_uri`` key then the item is
              considered "new" and is handled like a ``POST`` to the resource list.

            * If the dict has a ``resource_uri`` key and the ``resource_uri`` refers
              to an existing resource then the item is a update; it's treated
              like a ``PATCH`` to the corresponding resource detail.

            * If the dict has a ``resource_uri`` but the resource *doesn't* exist,
              then this is considered to be a create-via-``PUT``.

        Each entry in ``deleted_objects`` referes to a resource URI of an existing
        resource to be deleted; each is handled like a ``DELETE`` to the relevent
        resource.

        In any case:

            * If there's a resource URI it *must* refer to a resource of this
              type. It's an error to include a URI of a different resource.

            * ``PATCH`` is all or nothing. If a single sub-operation fails, the
              entire request will fail and all resources will be rolled back.
        """
        request = self.convert_post_to_patch(request)
        deserialized = self.deserialize(request, request.raw_post_data, format=request.META.get('CONTENT_TYPE', 'application/json'))

        if "objects" not in deserialized:
            raise BadRequest("Invalid data sent.")

        if len(deserialized["objects"]) and 'put' not in self._meta.detail_allowed_methods:
            raise ImmediateHttpResponse(response=http.HttpMethodNotAllowed())

        for data in deserialized["objects"]:
            # If there's a resource_uri then this is either an
            # update-in-place or a create-via-PUT.
            if "resource_uri" in data:
                uri = data.pop('resource_uri')

                try:
                    obj = self.get_via_uri(uri, request=request)

                    # The object does exist, so this is an update-in-place.
                    bundle = self.build_bundle(obj=obj, request=request)
                    bundle = self.full_dehydrate(bundle)
                    bundle = self.alter_detail_data_to_serialize(request, bundle)
                    self.update_in_place(request, bundle, data)
                except (ObjectDoesNotExist, MultipleObjectsReturned):
                    # The object referenced by resource_uri doesn't exist,
                    # so this is a create-by-PUT equivalent.
                    data = self.alter_deserialized_detail_data(request, data)
                    bundle = self.build_bundle(data=dict_strip_unicode_keys(data))
                    bundle.obj.pk = obj.pk
                    self.is_valid(bundle, request)
                    self.obj_create(bundle, request=request)
            else:
                # There's no resource URI, so this is a create call just
                # like a POST to the list resource.
                data = self.alter_deserialized_detail_data(request, data)
                bundle = self.build_bundle(data=dict_strip_unicode_keys(data))
                self.is_valid(bundle, request)
                self.obj_create(bundle, request=request)

        if len(deserialized.get('deleted_objects', [])) and 'delete' not in self._meta.detail_allowed_methods:
            raise ImmediateHttpResponse(response=http.HttpMethodNotAllowed())

        for uri in deserialized.get('deleted_objects', []):
            obj = self.get_via_uri(uri, request=request)
            self.obj_delete(request=request, _obj=obj)

        return http.HttpAccepted()

    def patch_detail(self, request, **kwargs):
        """
        Updates a resource in-place.

        Calls ``obj_update``.

        If the resource is updated, return ``HttpAccepted`` (202 Accepted).
        If the resource did not exist, return ``HttpNotFound`` (404 Not Found).
        """
        request = self.convert_post_to_patch(request)

        # We want to be able to validate the update, but we can't just pass
        # the partial data into the validator since all data needs to be
        # present. Instead, we basically simulate a PUT by pulling out the
        # original data and updating it in-place.
        # So first pull out the original object. This is essentially
        # ``get_detail``.
        try:
            obj = self.cached_obj_get(request=request, **self.remove_api_resource_names(kwargs))
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one resource is found at this URI.")

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)

        # Now update the bundle in-place.
        deserialized = self.deserialize(request, request.raw_post_data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        self.update_in_place(request, bundle, deserialized)
        return http.HttpAccepted()

    def update_in_place(self, request, original_bundle, new_data):
        """
        Update the object in original_bundle in-place using new_data.
        """
        original_bundle.data.update(**dict_strip_unicode_keys(new_data))

        # Now we've got a bundle with the new data sitting in it and we're
        # we're basically in the same spot as a PUT request. SO the rest of this
        # function is cribbed from put_detail.
        self.alter_deserialized_detail_data(request, original_bundle.data)
        self.is_valid(original_bundle, request)
        return self.obj_update(original_bundle, request=request, pk=original_bundle.obj.pk)

    def get_schema(self, request, **kwargs):
        """
        Returns a serialized form of the schema of the resource.

        Calls ``build_schema`` to generate the data. This method only responds
        to HTTP GET.

        Should return a HttpResponse (200 OK).
        """
        self.method_check(request, allowed=['get'])
        self.is_authenticated(request)
        self.throttle_check(request)
        self.log_throttled_access(request)
        return self.create_response(request, self.build_schema())

    def get_multiple(self, request, **kwargs):
        """
        Returns a serialized list of resources based on the identifiers
        from the URL.

        Calls ``obj_get`` to fetch only the objects requested. This method
        only responds to HTTP GET.

        Should return a HttpResponse (200 OK).
        """
        self.method_check(request, allowed=['get'])
        self.is_authenticated(request)
        self.throttle_check(request)

        # Rip apart the list then iterate.
        obj_pks = kwargs.get('pk_list', '').split(';')
        objects = []
        not_found = []

        for pk in obj_pks:
            try:
                obj = self.obj_get(request, pk=pk)
                bundle = self.build_bundle(obj=obj, request=request)
                bundle = self.full_dehydrate(bundle)
                objects.append(bundle)
            except ObjectDoesNotExist:
                not_found.append(pk)

        object_list = {
            'objects': objects,
        }

        if len(not_found):
            object_list['not_found'] = not_found

        self.log_throttled_access(request)
        return self.create_response(request, object_list)

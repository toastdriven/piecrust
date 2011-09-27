========
Piecrust
========

Creating delicious APIs for Python apps since 2010.

Currently in beta (v1.0.0-beta) but being used actively in production on several
sites.


Requirements
============

Required
--------

* Python 2.5+
* mimeparse 0.1.3+ (http://code.google.com/p/mimeparse/)

  * Older versions will work, but their behavior on JSON/JSONP is a touch wonky.

* dateutil (http://labix.org/python-dateutil) >= 1.5, < 2.0

Optional
--------

* python_digest (https://bitbucket.org/akoha/python-digest/)
* lxml (http://codespeak.net/lxml/) if using the XML serializer
* pyyaml (http://pyyaml.org/) if using the YAML serializer
* biplist (http://explorapp.com/biplist/) if using the binary plist serializer


What's It Look Like?
====================

A basic example looks like::

    # myapp/api.py
    # ============
    from piecrust import fields
    from piecrust.resources import Resource


    class EntryResource(Resource):
        title = fields.CharField(attribute='title')


        class Meta:
            resource_name = 'entry'
            object_class = Entry
            authorization = Authorization()

That gets you a fully working, read-write API for the ``Entry`` object that
supports all CRUD operations in a RESTful way. JSON/XML/YAML support is already
there, and it's easy to add related data/authentication/caching.

You can find more in the documentation at
http://piecrust.readthedocs.org/.


Why Piecrust?
=============

Lots of people do REST different ways. Piecrust is an attempt to unify how
REST is done regardless of what framework you choose or what data source you
pull from.

It was extracted out of Tastypie_ and as a result, much of the code has be in
production and battle-tested.

Reasons to use Piecrust include:

* You need an API that is RESTful and uses HTTP well.
* You want to support deep relations.
* You DON'T want to have to write your own serializer to make the output right.
* You want an API framework that has little magic, very flexible and maps well to
  the problem domain.
* You want/need XML serialization that is treated equally to JSON (and YAML is
  there too).

.. _Tastypie: http://github.com/toastdriven/django-tastypie


Reference Material
==================

* http://en.wikipedia.org/wiki/REST
* http://en.wikipedia.org/wiki/List_of_HTTP_status_codes
* http://www.ietf.org/rfc/rfc2616.txt
* http://jacobian.org/writing/rest-worst-practices/

:author: Daniel Lindsley
:date: 2011/09/26

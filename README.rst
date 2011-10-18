======================
Project Status: Failed
======================

The goal here was to try to provide a framework-agnostic REST API layer for
all Python libraries. Think Tastypie_ abstracted for all to use.

It's frighteningly close to done (just some cleanup in ``resources.py`` to
remove the last bits of Django & delegate to the URIHandler, then updating
tests & docs), but I won't be finishing it.

The problem is that, while the idea of consistent API interfaces across
frameworks & heavily-pluggable sounds good, the actual implementation... hurts.
Everything has to be abstracted so far away that it'd be little use
out-of-the-box, which is where Tastypie shines.

In addition, I wouldn't ever use it, beyond integrating it into Tastypie.
Beyond that, I don't think adoption would be good enough to justify it.

You're welcome to poke at it or fork it (keep in mind the LICENSE please),
but I won't be completing it nor supporting it. YMMV. Must be 18 years of age
or older. Only one per household. Offer void Oct. 18, 2011.

.. _Tastypie: http://github.com/toastdriven/django-tastypie

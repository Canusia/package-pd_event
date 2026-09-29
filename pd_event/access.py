"""Role gates applied to every CE and faculty route in urls/.

The page views were written for the CE office and act on whatever record id
they are sent, so a route without a gate is open to every logged-in user --
a student could delete an event. Gating at the URL keeps the rule in one
place per portal instead of in each view.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(check):
    """Wrap a view so users failing `check(user)` get 403.

    Anonymous users still get the login redirect from the project's
    LoginRequiredMiddleware before this runs.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def ce_only(user):
    from cis.utils import user_has_cis_role
    return user_has_cis_role(user)


def ce_or_faculty(user):
    from cis.utils import user_has_cis_role, user_has_faculty_role
    return user_has_cis_role(user) or user_has_faculty_role(user)


def gate_urlpatterns(urlpatterns, check, public=()):
    """Apply role_required(check) to every function-view route, except the
    route names in `public` and included URLconfs (the API router gates
    its viewsets itself)."""
    from django.urls import URLPattern

    for pattern in urlpatterns:
        if not isinstance(pattern, URLPattern) or pattern.name in public:
            continue
        if hasattr(pattern.callback, 'view_class'):
            # Class-based views (e.g. JavaScriptCatalog) serve no records.
            continue
        pattern.callback = role_required(check)(pattern.callback)
    return urlpatterns

MyCE - PD Event
====================

Setup
-----

In ``INSTALLED_APPS`` (supports both pip-installed and editable-submodule layouts)::

    import importlib.util

    INSTALLED_APPS += [
        'pd_event.pd_event.apps.DevPdEventConfig'
        if importlib.util.find_spec('pd_event.pd_event')
        else 'pd_event.apps.PdEventConfig',
    ]

In ``STATICFILES_DIRS``::

    os.path.join(get_package_path("pd_event.pd_event"), 'staticfiles')
    if importlib.util.find_spec('pd_event.pd_event')
    else os.path.join(get_package_path("pd_event"), 'staticfiles') if get_package_path("pd_event") else None,

If ``get_package_path`` is not defined in your project::

    import importlib.util

    def get_package_path(package_name):
        """Dynamically find package installation path."""
        spec = importlib.util.find_spec(package_name)
        return os.path.dirname(spec.origin) if spec else None

In ``myce/urls.py``, pick the namespace based on layout::

    _pde = 'pd_event.pd_event' if importlib.util.find_spec('pd_event.pd_event') else 'pd_event'

    urlpatterns += [
        path('ce/events/', include(f'{_pde}.urls.ce')),
        path('faculty/events/', include(f'{_pde}.urls.faculty')),
        path('instructor/events/', include(f'{_pde}.urls.instructor')),
    ]

Routes
------

- ``/ce/events/`` — admin/CE portal (full event + attendee management, PD letters, sign-in sheets, info sessions)
- ``/faculty/events/`` — faculty portal (limited view)
- ``/instructor/events/`` — instructor portal (read-only list of events the instructor is a guest of; PD letter download when attendance is marked ``attended``)

Instructor portal
-----------------

The instructor page (``pd_event_instructor:index``) is backed by a DRF
``ReadOnlyModelViewSet`` (``pd_event_instructor:attendees-list``) registered at
``/instructor/events/api/attendees/``. It uses ``rest_framework_datatables``
with ``serverSide: true`` for paging/sorting/searching.

Default sort: term descending, then event start time descending.

Permission: ``cis.utils.INSTRUCTOR_user_only`` on the API; ``@login_required``
on the page view. The queryset filters by ``request.user.teacher`` so an
instructor can only see their own attendee records.

"""Dashboard messages (#15). Registered through cis.page_messages, which
cis autodiscovers. The CE dashboard shows them once cis renders
('ce', 'dashboard') messages; the HS admin dashboard does today."""
import datetime

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from cis.page_messages import PageMessage, page_message


def _url(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return ''


@page_message('ce', 'dashboard')
def ce_dashboard(request):
    """Upcoming events, and ended events that still need attendance marked."""
    from types import SimpleNamespace

    from .models import Event, EventAttendee
    from .services.summary import KEY_NOT_MARKED, status_key

    now = timezone.now()
    out = []
    # One query: guest rows of events that ended in the last 90 days.
    need = {event_id for event_id, meta in EventAttendee.objects.filter(
        event__end_time__lte=now,
        event__end_time__gte=now - datetime.timedelta(days=90),
    ).values_list('event_id', 'meta')
        if status_key(SimpleNamespace(meta=meta or {})) == KEY_NOT_MARKED}
    link = _url('pd_event:events')
    if need:
        out.append(PageMessage(
            text=(f'{len(need)} PD event{"s" if len(need) != 1 else ""} '
                  f'need attendance marked.'),
            level='warning', url=link))
    upcoming = Event.objects.filter(start_time__gte=now,
                                    start_time__lte=now + datetime.timedelta(days=14)).count()
    if upcoming:
        out.append(PageMessage(
            text=f'{upcoming} PD event{"s" if upcoming != 1 else ""} in the next two weeks.',
            level='info', url=link))
    return out


@page_message('highschool_admin', 'dashboard')
def hs_admin_dashboard(request):
    """Instructors at the admin's schools who missed a required PD event."""
    from .services.summary import school_history
    from .views.highschool_admin import admin_highschool_ids

    try:
        highschool_ids = admin_highschool_ids(request)
    except Exception:
        return None
    if not highschool_ids:
        return None
    missed = {tuple(r['person'][:2]) for r in school_history(highschool_ids)['rows']
              if r['required_missed']}
    if not missed:
        return None
    n = len(missed)
    return [PageMessage(
        text=(f'{n} teacher{"s" if n != 1 else ""} at your school missed a required '
              f'PD event.'),
        level='warning', url=_url('pd_event_highschool_admin:events'))]

"""HS admin portal: PD events of the admin's own schools' instructors (#15).

Mounted by the host at ``highschool_admin/events/`` (``urls/highschool_admin.py``,
namespace ``pd_event_highschool_admin``).
"""
import importlib.util

from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def _hsadmin_helpers():
    """highschool_admin's helpers, nested (editable) or flat layout."""
    if importlib.util.find_spec('highschool_admin.highschool_admin'):
        from highschool_admin.highschool_admin.views import utils
    else:
        from highschool_admin.views import utils
    return utils


def admin_highschool_ids(request):
    if not request.user.is_authenticated or not request.user.groups.filter(
            name='highschool_admin').exists():
        raise PermissionDenied
    return list(_hsadmin_helpers().get_user_highschools(request).values_list('id', flat=True))


def events(request):
    from cis.menu import draw_menu
    from cis.models.term import Term
    from ..services.summary import school_history

    highschool_ids = admin_highschool_ids(request)
    term_id = request.GET.get('term') or None
    history = school_history(highschool_ids, term_id=term_id)
    terms = Term.objects.filter(
        event__eventattendee__course_certificate__teacher_highschool__highschool_id__in=highschool_ids
    ).distinct().order_by('-code', 'label')

    return render(request, 'pd_event/highschool_admin/events.html', {
        'page_title': 'PD Events',
        'menu': draw_menu(_hsadmin_helpers().get_hsadmin_menu(), 'pd_events', '', 'highschool_admin'),
        'history': history,
        'terms': terms,
        'term_id': term_id,
    })

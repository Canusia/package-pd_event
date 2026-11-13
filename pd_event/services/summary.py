"""Attendance summaries for CE (#9): one event, and a term's events.

Attendance lives in ``EventAttendee.meta``:

- ``attendance_status``: ``'attended'``, ``'not attended'``, or anything else
  (``'N/A'`` when added) for not marked yet.
- ``attendance_type``: ``'required'`` or ``'optional'``.
- ``pd_hour``: hours earned. The inline edit saves it as a string.
- ``pd_letter_sent_on``: set when a PD letter is emailed.

Counts are per guest-list row. An instructor on the list for two of the
event's courses has two rows (see the duplicate-invites issue).
"""
from collections import OrderedDict

ATTENDED = 'attended'
NOT_ATTENDED = 'not attended'

# status_key values, shared with the Manage Attendance filters.
KEY_ATTENDED = 'attended'
KEY_NOT_ATTENDED = 'not_attended'
KEY_NOT_MARKED = 'not_marked'

STATUS_LABELS = {
    KEY_ATTENDED: 'Attended',
    KEY_NOT_ATTENDED: 'Not Attended',
    KEY_NOT_MARKED: 'Not Marked',
}

ATTENDEE_RELATED = (
    'course_certificate__course',
    'course_certificate__teacher_highschool__highschool',
    'course_certificate__teacher_highschool__teacher__user',
)


def status_key(attendee):
    status = ((attendee.meta or {}).get('attendance_status') or '').strip().lower()
    if status == ATTENDED:
        return KEY_ATTENDED
    if status == NOT_ATTENDED:
        return KEY_NOT_ATTENDED
    return KEY_NOT_MARKED


def attendance_type_key(attendee):
    return ((attendee.meta or {}).get('attendance_type') or '').strip().lower()


def is_required_missed(attendee):
    return attendance_type_key(attendee) == 'required' and status_key(attendee) == KEY_NOT_ATTENDED


def pd_hours(attendee):
    """Hours this attendee earned: 0 unless attended."""
    if status_key(attendee) != KEY_ATTENDED:
        return 0.0
    try:
        return float((attendee.meta or {}).get('pd_hour') or 0)
    except (TypeError, ValueError):
        return 0.0


def gets_letter(attendee):
    """A PD letter is owed to an instructor/faculty attendee who attended."""
    return attendee.type != 'highschool' and status_key(attendee) == KEY_ATTENDED


def letter_sent_on(attendee):
    return (attendee.meta or {}).get('pd_letter_sent_on') or ''


def school_and_course(attendee):
    """(school name, course name) for an instructor row, else ('', '')."""
    cert = attendee.course_certificate if attendee.course_certificate_id else None
    if cert is None:
        return '', ''
    try:
        school = cert.teacher_highschool.highschool.name
    except AttributeError:
        school = ''
    course = cert.course.name if cert.course_id else ''
    return school or '', course or ''


def person(attendee):
    """(last name, first name, email). Instructor rows read the course
    certificate: their meta 'id' is the certificate id, which
    EventAttendee.get_info() looks up as a Teacher id and misses."""
    cert = attendee.course_certificate if attendee.course_certificate_id else None
    if cert is not None:
        try:
            user = cert.teacher_highschool.teacher.user
            return user.last_name or '', user.first_name or '', user.email or ''
        except AttributeError:
            pass
    info = attendee.get_info() or {}
    return info.get('last_name', '') or '', info.get('first_name', '') or '', info.get('email', '') or ''


def teacher_id(attendee):
    cert = attendee.course_certificate if attendee.course_certificate_id else None
    try:
        return cert.teacher_highschool.teacher_id if cert else None
    except AttributeError:
        return None


def rate(part, whole):
    """Whole-number percentage, or None when there is nothing to divide."""
    return round(100 * part / whole) if whole else None


def _round_hours(value):
    value = round(value, 2)
    return int(value) if value == int(value) else value


def _breakdown(groups):
    """Rows for {name: [attendees]}: least engaged first, then by name."""
    rows = []
    for name, people in groups.items():
        attended = sum(1 for a in people if status_key(a) == KEY_ATTENDED)
        rows.append({
            'name': name,
            'invited': len(people),
            'attended': attended,
            'required_missed': sum(1 for a in people if is_required_missed(a)),
            'rate': rate(attended, len(people)),
        })
    rows.sort(key=lambda r: (r['rate'] if r['rate'] is not None else 101, r['name']))
    return rows


def summarize(attendees):
    """The numbers behind the summary cards for a list of attendee rows."""
    attendees = list(attendees)
    counts = {KEY_ATTENDED: 0, KEY_NOT_ATTENDED: 0, KEY_NOT_MARKED: 0}
    by_school, by_course = OrderedDict(), OrderedDict()
    summary = {'required': 0, 'optional': 0, 'required_missed': 0, 'pd_hours': 0.0,
               'letters_sent': 0, 'letters_owed': 0}
    teachers = set()

    for a in attendees:
        key = status_key(a)
        counts[key] += 1
        kind = attendance_type_key(a)
        if kind in ('required', 'optional'):
            summary[kind] += 1
        if is_required_missed(a):
            summary['required_missed'] += 1
        summary['pd_hours'] += pd_hours(a)
        if gets_letter(a):
            summary['letters_sent' if letter_sent_on(a) else 'letters_owed'] += 1
        school, course = school_and_course(a)
        if school:
            by_school.setdefault(school, []).append(a)
        if course:
            by_course.setdefault(course, []).append(a)
        if key == KEY_ATTENDED and teacher_id(a):
            teachers.add(teacher_id(a))

    invited = len(attendees)
    summary.update({
        'invited': invited,
        'attended': counts[KEY_ATTENDED],
        'not_attended': counts[KEY_NOT_ATTENDED],
        'not_marked': counts[KEY_NOT_MARKED],
        'marked': counts[KEY_ATTENDED] + counts[KEY_NOT_ATTENDED],
        'rate': rate(counts[KEY_ATTENDED], invited),
        'pd_hours': _round_hours(summary['pd_hours']),
        'schools': len(by_school),
        'courses': len(by_course),
        'instructors': len(teachers),
        'by_school': _breakdown(by_school),
        'by_course': _breakdown(by_course),
    })
    return summary


def event_attendees(event):
    from ..models import EventAttendee
    return EventAttendee.objects.filter(event=event).select_related(*ATTENDEE_RELATED)


def event_summary(event):
    summary = summarize(event_attendees(event))
    summary['total_cost'] = None
    try:
        from cis.settings.pd_event import pd_event as pd_settings
        if pd_settings.from_db().get('track_pd_event_cost') and event.cost_per_attendee:
            summary['total_cost'] = round(event.cost_per_attendee * summary['attended'], 2)
    except Exception:  # settings unavailable: no cost card
        pass
    return summary


def term_attendees(term_ids=None):
    from ..models import EventAttendee
    records = EventAttendee.objects.select_related('event__term', 'event__event_type',
                                                   *ATTENDEE_RELATED)
    if term_ids is not None:
        records = records.filter(event__term_id__in=term_ids)
    return records


def by_term():
    """One row per term that has events: events, guests and outcomes."""
    from ..models import Event
    events = {}
    for event in Event.objects.select_related('term').order_by('-term__code'):
        events.setdefault(event.term_id, {'term': event.term, 'events': 0})['events'] += 1
    attendees = {}
    for a in term_attendees(list(events)):
        attendees.setdefault(a.event.term_id, []).append(a)

    rows = []
    for term_id, info in events.items():
        s = summarize(attendees.get(term_id, []))
        rows.append({
            'term_id': str(term_id),
            'term': str(info['term'].label),
            'term_code': info['term'].code,
            'events': info['events'],
            'invited': s['invited'],
            'attended': s['attended'],
            'not_marked': s['not_marked'],
            'rate': s['rate'],
            'required_missed': s['required_missed'],
            'pd_hours': s['pd_hours'],
            'instructors': s['instructors'],
        })
    return rows


def term_detail(term):
    """A term's breakdowns: by event type, course and school, and its events."""
    from ..models import Event
    attendees = list(term_attendees([term.id]))
    by_type, by_event = OrderedDict(), OrderedDict()
    for a in attendees:
        by_type.setdefault(a.event.event_type.name, []).append(a)
        by_event.setdefault(a.event_id, []).append(a)

    events = []
    for event in Event.objects.filter(term=term).select_related('event_type').order_by('-start_time'):
        s = summarize(by_event.get(event.id, []))
        events.append({
            'id': str(event.id), 'name': event.name or str(event.event_type),
            'event_type': event.event_type.name,
            'start_time': (event.start_time_local.strftime('%m/%d/%Y %I:%M %p')
                           if event.start_time else ''),
            'invited': s['invited'], 'attended': s['attended'], 'rate': s['rate'],
            'not_marked': s['not_marked'], 'required_missed': s['required_missed'],
            'url': str(event.ce_url),
        })
    total = summarize(attendees)
    return {
        'term': str(term.label),
        'by_event_type': _breakdown(by_type),
        'by_course': total['by_course'],
        'by_school': total['by_school'],
        'events': events,
    }


def required_missed(term):
    """Attendee rows marked Not Attended on a required event in the term."""
    return [a for a in term_attendees([term.id]).order_by('event__start_time')
            if is_required_missed(a)]

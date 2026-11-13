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
import math
from collections import OrderedDict
from types import SimpleNamespace

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


def rsvp_key(attendee):
    """'confirmed', 'declined' or '' (no reply yet) (#14)."""
    answer = ((attendee.meta or {}).get('rsvp') or '').strip().lower()
    return answer if answer in ('confirmed', 'declined') else ''


def is_required_missed(attendee):
    return attendance_type_key(attendee) == 'required' and status_key(attendee) == KEY_NOT_ATTENDED


def pd_hours(attendee):
    """Hours this attendee earned: 0 unless attended."""
    if status_key(attendee) != KEY_ATTENDED:
        return 0.0
    try:
        hours = float((attendee.meta or {}).get('pd_hour') or 0)
    except (TypeError, ValueError):
        return 0.0
    # The inline edit saves raw text: 'nan' and 'inf' parse as floats.
    return hours if math.isfinite(hours) else 0.0


def gets_letter(attendee):
    """A PD letter is owed to a person guest who attended (#12): an
    instructor with a course certificate, or high school personnel, faculty
    or a cohort participant whose record still exists. High school rows
    record a head count, not a person."""
    if status_key(attendee) != KEY_ATTENDED:
        return False
    if attendee.type == 'instructor':
        return bool(attendee.course_certificate_id)
    if attendee.type in ('highschool_admin', 'cohort_participant', 'faculty'):
        return attendee.recipient() is not None
    return False


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
    certificate directly (one less query than get_info())."""
    cert = attendee.course_certificate if attendee.course_certificate_id else None
    if cert is not None:
        try:
            user = cert.teacher_highschool.teacher.user
            return user.last_name or '', user.first_name or '', user.email or ''
        except AttributeError:
            pass
    info = attendee.get_info() or {}
    return info.get('last_name', '') or '', info.get('first_name', '') or '', info.get('email', '') or ''


def person_key(attendee):
    """Who a guest row is: an instructor by teacher (any of their course
    certificates), anyone else by type and record id (#10)."""
    tid = teacher_id(attendee)
    if tid:
        return ('teacher', tid)
    return (attendee.type, str((attendee.meta or {}).get('id', attendee.pk)))


def courses_of(attendee):
    """The courses an instructor guest was invited for: meta['courses'] when
    invites were combined (#10), else the certificate's course."""
    courses = (attendee.meta or {}).get('courses')
    if courses:
        return list(courses)
    _, course = school_and_course(attendee)
    return [course] if course else []


STATUS_RANK = {KEY_ATTENDED: 0, KEY_NOT_ATTENDED: 1, KEY_NOT_MARKED: 2}


def merge_duplicates(event):
    """Combine guest rows for the same person into one (#10). Keeps the
    strongest row (attended, then not attended, then not marked; a sent
    letter wins a tie); required if any was; courses, notes, hours and the
    letter date are carried over. Returns the number of rows removed."""
    groups = OrderedDict()
    for a in event_attendees(event).order_by('id'):
        groups.setdefault(person_key(a), []).append(a)

    removed = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda a: (STATUS_RANK[status_key(a)], not letter_sent_on(a)))
        keep, others = rows[0], rows[1:]
        meta = dict(keep.meta or {})
        courses, notes = [], []
        for a in rows:
            for course in courses_of(a):
                if course not in courses:
                    courses.append(course)
            note = ((a.meta or {}).get('note') or '').strip()
            if note and note not in notes:
                notes.append(note)
        if any(attendance_type_key(a) == 'required' for a in rows):
            meta['attendance_type'] = 'required'
        meta['courses'] = courses
        if notes:
            meta['note'] = '; '.join(notes)
        if not meta.get('pd_letter_sent_on'):
            sent = [letter_sent_on(a) for a in others if letter_sent_on(a)]
            if sent:
                meta['pd_letter_sent_on'] = sent[0]
        if status_key(keep) == KEY_ATTENDED:
            meta['pd_hour'] = max([pd_hours(a) for a in rows] + [pd_hours(keep)])
        for a in others:
            a.delete()
            removed += 1
        keep.meta = meta
        keep.save()
    return removed


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
    people = set()

    rsvps = {'confirmed': 0, 'declined': 0, '': 0}
    no_shows = 0
    for a in attendees:
        people.add(person_key(a))
        rsvps[rsvp_key(a)] += 1
        if rsvp_key(a) == 'confirmed' and status_key(a) == KEY_NOT_ATTENDED:
            no_shows += 1
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
        school, _ = school_and_course(a)
        if school:
            by_school.setdefault(school, []).append(a)
        for course in courses_of(a):  # every course on a combined invite (#10)
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
        # Extra rows for a person already on the list (#10).
        'duplicates': invited - len(people),
        # RSVPs (#14): a no-show confirmed and was marked Not Attended.
        'confirmed': rsvps['confirmed'],
        'declined': rsvps['declined'],
        'no_reply': rsvps[''],
        'no_shows': no_shows,
        'by_school': _breakdown(by_school),
        'by_course': _breakdown(by_course),
    })
    return summary


def event_attendees(event):
    from ..models import EventAttendee
    return EventAttendee.objects.filter(event=event).select_related(*ATTENDEE_RELATED)


def track_cost():
    """The PD event setting 'Track PD event cost'."""
    try:
        from cis.settings.pd_event import pd_event as pd_settings
        return bool(pd_settings.from_db().get('track_pd_event_cost'))
    except Exception:  # settings unavailable
        return False


def event_summary(event):
    summary = summarize(event_attendees(event))
    summary['total_cost'] = None
    if track_cost() and event.cost_per_attendee:
        summary['total_cost'] = round(event.cost_per_attendee * summary['attended'], 2)
    return summary


def term_attendees(term_ids=None):
    from ..models import EventAttendee
    records = EventAttendee.objects.select_related('event__term', 'event__event_type',
                                                   *ATTENDEE_RELATED)
    if term_ids is not None:
        records = records.filter(event__term_id__in=term_ids)
    return records


def by_term():
    """One row per term that has events: events, guests and outcomes.

    Reads only each guest row's meta and teacher id (no model instances), so
    the tab stays light on tenants with years of events.
    """
    from ..models import Event, EventAttendee
    events = OrderedDict()
    for term_id, label, code in (Event.objects.order_by('-term__code')
                                 .values_list('term_id', 'term__label', 'term__code')):
        events.setdefault(term_id, {'label': label, 'code': code, 'events': 0})['events'] += 1
    prior_of = _prior_terms(events)

    totals = {}
    rows = (EventAttendee.objects.filter(event__term_id__in=list(events))
            .values_list('event__term_id', 'meta',
                         'course_certificate__teacher_highschool__teacher_id'))
    for term_id, meta, teacher in rows.iterator():
        guest = SimpleNamespace(meta=meta or {})
        t = totals.setdefault(term_id, {'invited': 0, 'attended': 0, 'not_marked': 0,
                                        'required_missed': 0, 'pd_hours': 0.0,
                                        'teachers': set()})
        key = status_key(guest)
        t['invited'] += 1
        if key == KEY_ATTENDED:
            t['attended'] += 1
            if teacher:
                t['teachers'].add(teacher)
        elif key == KEY_NOT_MARKED:
            t['not_marked'] += 1
        if is_required_missed(guest):
            t['required_missed'] += 1
        t['pd_hours'] += pd_hours(guest)

    out = []
    for term_id, info in events.items():
        t = totals.get(term_id, {'invited': 0, 'attended': 0, 'not_marked': 0,
                                 'required_missed': 0, 'pd_hours': 0.0, 'teachers': set()})
        out.append({
            'term_id': str(term_id),
            'term': str(info['label']),
            'term_code': info['code'],
            'events': info['events'],
            'invited': t['invited'],
            'attended': t['attended'],
            'not_marked': t['not_marked'],
            'rate': rate(t['attended'], t['invited']),
            'required_missed': t['required_missed'],
            'pd_hours': _round_hours(t['pd_hours']),
            'instructors': len(t['teachers']),
        })

    # The same term a year earlier (#17), when it had events.
    by_id = {row['term_id']: row for row in out}
    for row in out:
        prior = by_id.get(str(prior_of.get(row['term_id']) or ''))
        row['prior'] = {key: prior[key] for key in (
            'term_id', 'term', 'events', 'invited', 'attended', 'rate', 'not_marked',
            'required_missed', 'pd_hours', 'instructors')} if prior else None
    return out


def _prior_terms(term_ids):
    """{term id (str): id of the same term a year earlier}.

    "The same term" is the same code (codes repeat each academic year); "a
    year earlier" is the latest earlier academic year of the same campus,
    by start date and then by name.
    """
    import datetime

    from cis.models.term import Term

    terms = list(Term.objects.filter(
        code__in=Term.objects.filter(id__in=list(term_ids)).values('code'))
        .values('id', 'code', 'academic_year__name', 'academic_year__hs_start_date',
                'academic_year__campus_id'))

    def year_key(t):
        return (t['academic_year__hs_start_date'] or datetime.date.min,
                t['academic_year__name'] or '')

    prior = {}
    wanted = {str(i) for i in term_ids}
    for t in terms:
        if str(t['id']) not in wanted:
            continue
        earlier = [o for o in terms
                   if o['code'] == t['code']
                   and o['academic_year__campus_id'] == t['academic_year__campus_id']
                   and year_key(o) < year_key(t)]
        if earlier:
            prior[str(t['id'])] = max(earlier, key=year_key)['id']
    return prior


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


def _history_row(a):
    event = a.event
    key = status_key(a)
    return {
        'id': str(a.id),
        'event': event.name or str(event.event_type),
        'event_type': event.event_type.name,
        'event_url': str(event.ce_url),
        'term': event.term.label,
        'term_id': str(event.term_id),
        'start': event.start_time_local if event.start_time else None,
        'courses': courses_of(a),
        'school': school_and_course(a)[0],
        'person': person(a),
        'status_key': key,
        'status': STATUS_LABELS[key],
        'attendance_type': attendance_type_key(a) or '',
        'required_missed': is_required_missed(a),
        'pd_hours': _round_hours(pd_hours(a)),
        'letter_sent_on': letter_sent_on(a),
        'pd_letter_url': str(a.pd_url) if gets_letter(a) else '',
    }


def history(rows):
    """Guest rows -> {'rows': [...newest first], 'terms': [per-term totals]}."""
    import datetime
    oldest = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    rows = sorted(rows, key=lambda a: a.event.start_time or oldest, reverse=True)
    out = [_history_row(a) for a in rows]
    terms = OrderedDict()
    for row in out:
        t = terms.setdefault(row['term_id'], {
            'term': row['term'], 'events': 0, 'attended': 0, 'required_missed': 0,
            'pd_hours': 0})
        t['events'] += 1
        t['attended'] += row['status_key'] == KEY_ATTENDED
        t['required_missed'] += row['required_missed']
        t['pd_hours'] = _round_hours(t['pd_hours'] + row['pd_hours'])
    return {'rows': out, 'terms': list(terms.values())}


HISTORY_RELATED = ('event__term', 'event__event_type') + ATTENDEE_RELATED


def teacher_history(teacher):
    """An instructor's PD events, every course certificate (#15)."""
    from ..models import EventAttendee
    return history(EventAttendee.objects.filter(
        course_certificate__teacher_highschool__teacher=teacher
    ).select_related(*HISTORY_RELATED))


def school_history(highschool_ids, term_id=None):
    """PD events of the instructors at these high schools (#15)."""
    from ..models import EventAttendee
    rows = EventAttendee.objects.filter(
        course_certificate__teacher_highschool__highschool_id__in=list(highschool_ids)
    ).select_related(*HISTORY_RELATED)
    if term_id:
        rows = rows.filter(event__term_id=term_id)
    return history(rows)

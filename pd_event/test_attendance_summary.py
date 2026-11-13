"""Attendance summaries for CE (package-pd_event#9).

The event summary (cards above the event tabs), the Manage Attendance feed,
"mark everyone unmarked" / "send letters still owed", the events-list
counts and status, and the By Term rollup.
"""
import csv
import io
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from cis.models import (
    CustomUser, HighSchool, Teacher, TeacherCourseCertificate, TeacherHighSchool, Term,
)
from cis.models.course import Cohort, Course
from cis.models.term import AcademicYear

from .models import Event, EventAttendee, EventType

ATTENDED, NOT_ATTENDED, UNMARKED = 'attended', 'not attended', 'N/A'


def _u(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class _Fixture(TestCase):
    """One past event with six instructor guests at two schools, two courses.

    Ann (North, ENG)  required  attended      pd 3.0, letter sent
    Bob (North, ENG)  required  not attended  -> required missed
    Cat (South, ENG)  optional  attended      pd '2.5' (string, as update_count saves it)
    Dan (South, MTH)  optional  not attended
    Eve (South, MTH)  required  not marked
    Fay (North, MTH)  optional  not marked
    """

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'instructor'):
            Group.objects.get_or_create(name=name)
        cls.ce_user = CustomUser.objects.create_user(
            username=_u('ce'), email=f'{_u("ce")}@x.com', password='x')
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

        cls.north = HighSchool.objects.create(name='North High', code=_u('N'))
        cls.south = HighSchool.objects.create(name='South High', code=_u('S'))
        cohort = Cohort.objects.create(designator=_u('C')[:8], name=_u('Cohort'))
        cls.eng = Course.objects.create(cohort=cohort, catalog_number='101', title='Comp',
                                        name='ENG 101', credit_hours=3, status='Active')
        cls.mth = Course.objects.create(cohort=cohort, catalog_number='102', title='Alg',
                                        name='MTH 102', credit_hours=3, status='Active')
        ay = AcademicYear.objects.create(name=_u('AY'))
        cls.term = Term.objects.create(academic_year=ay, code=_u('F')[:10], label='Fall 2026')
        cls.other_term = Term.objects.create(academic_year=ay, code=_u('S')[:10], label='Spring 2027')
        cls.event_type = EventType.objects.create(name=_u('Workshop'))

        now = timezone.now()
        cls.event = Event.objects.create(
            name='Fall Workshop', event_type=cls.event_type, term=cls.term, pd_hour=3.0,
            start_time=now - timedelta(days=2), end_time=now - timedelta(days=2, hours=-3),
            created_by=cls.ce_user, delivery_mode='Online')

        def guest(first, school, course, attendance_type, status, **meta):
            user = CustomUser.objects.create_user(
                username=_u(first), email=f'{_u(first)}@x.com', password='x',
                first_name=first, last_name='Teacher')
            th = TeacherHighSchool.objects.create(
                teacher=Teacher.objects.create(user=user), highschool=school)
            cert = TeacherCourseCertificate.objects.create(teacher_highschool=th, course=course)
            return EventAttendee.objects.create(
                event=cls.event, course_certificate=cert, type='instructor',
                meta={'id': str(cert.certificate_id), 'attendance_type': attendance_type,
                      'attendance_status': status, 'pd_hour': 3.0, **meta})

        cls.ann = guest('Ann', cls.north, cls.eng, 'required', ATTENDED,
                        pd_letter_sent_on='11/01/2026')
        cls.bob = guest('Bob', cls.north, cls.eng, 'required', NOT_ATTENDED, pd_hour=0)
        cls.cat = guest('Cat', cls.south, cls.eng, 'optional', ATTENDED, pd_hour='2.5')
        cls.dan = guest('Dan', cls.south, cls.mth, 'optional', NOT_ATTENDED, pd_hour=0)
        cls.eve = guest('Eve', cls.south, cls.mth, 'required', UNMARKED)
        cls.fay = guest('Fay', cls.north, cls.mth, 'optional', UNMARKED)

    def _get(self, view, *args, user=None, **params):
        request = RequestFactory().get('/x', params)
        request.user = user or self.ce_user
        return view(request, *args)

    def _post(self, view, *args, user=None, **data):
        request = RequestFactory().post('/x', data)
        request.user = user or self.ce_user
        return view(request, *args)


class EventSummaryTests(_Fixture):
    def _summary(self):
        from .services.summary import event_summary
        return event_summary(self.event)

    def test_counts(self):
        s = self._summary()
        self.assertEqual(
            (s['invited'], s['required'], s['optional']), (6, 3, 3))
        self.assertEqual(
            (s['attended'], s['not_attended'], s['not_marked'], s['marked']), (2, 2, 2, 4))
        self.assertEqual(s['required_missed'], 1)

    def test_rate_is_attended_of_invited(self):
        self.assertEqual(self._summary()['rate'], 33)  # 2 of 6

    def test_pd_hours_earned_sums_attendees_hours(self):
        # 3.0 + '2.5': a string from the inline edit still counts.
        self.assertEqual(self._summary()['pd_hours'], 5.5)

    def test_letters_sent_and_owed(self):
        s = self._summary()
        self.assertEqual((s['letters_sent'], s['letters_owed']), (1, 1))

    def test_reach(self):
        s = self._summary()
        self.assertEqual((s['schools'], s['courses']), (2, 2))

    def test_breakdowns_least_engaged_first(self):
        s = self._summary()
        # Equal rates: by name.
        self.assertEqual(
            [(r['name'], r['invited'], r['attended'], r['rate']) for r in s['by_school']],
            [('North High', 3, 1, 33), ('South High', 3, 1, 33)])
        by_course = {r['name']: (r['invited'], r['attended'], r['rate']) for r in s['by_course']}
        self.assertEqual(by_course, {'ENG 101': (3, 2, 67), 'MTH 102': (3, 0, 0)})
        self.assertEqual(s['by_course'][0]['name'], 'MTH 102')  # lowest rate first

    def test_empty_event(self):
        from .services.summary import event_summary
        empty = Event.objects.create(event_type=self.event_type, term=self.term,
                                     created_by=self.ce_user)
        s = event_summary(empty)
        self.assertEqual((s['invited'], s['rate'], s['pd_hours']), (0, None, 0))

    def test_summary_view_renders_the_cards(self):
        from .views.event import event_summary_view
        html = self._get(event_summary_view, self.event.id).content.decode()
        for text in ('Invited', 'Required but missed', '4 of 6 marked', '33%', '5.5'):
            self.assertIn(text, html)

    def test_event_page_shows_the_summary(self):
        from .views.event import detail
        html = self._get(detail, self.event.id).content.decode()
        self.assertIn('id="event_summary"', html)
        self.assertIn('Required but missed', html)


class AttendeeFeedTests(_Fixture):
    def _rows(self):
        from .views.event import attendees
        return {r['name'].split(',')[1].strip(): r
                for r in json.loads(self._get(attendees, self.event.id).content)['data']}

    def test_rows_carry_keys_for_filters_and_labels(self):
        rows = self._rows()
        self.assertEqual(rows['Ann']['status_key'], 'attended')
        self.assertEqual(rows['Bob']['status_key'], 'not_attended')
        self.assertEqual(rows['Eve']['status_key'], 'not_marked')
        self.assertTrue(rows['Bob']['required_missed'])
        self.assertFalse(rows['Eve']['required_missed'])
        self.assertEqual(rows['Cat']['attendance_type_key'], 'optional')
        self.assertEqual((rows['Dan']['school'], rows['Dan']['course']), ('South High', 'MTH 102'))

    def test_letter_fields(self):
        rows = self._rows()
        self.assertEqual(rows['Ann']['pd_letter_sent_on'], '11/01/2026')
        self.assertEqual(rows['Cat']['pd_letter_sent_on'], '')
        self.assertEqual(rows['Cat']['pd_hour'], '2.5')


class BulkActionTests(_Fixture):
    def test_mark_unmarked_as_not_attended_leaves_marked_rows(self):
        from .views.event import mark_attendance
        resp = self._post(mark_attendance, self.event.id,
                          attendance_status='not attended', scope='unmarked')
        self.assertEqual(json.loads(resp.content)['status'], 'success')
        for guest, expected in ((self.eve, NOT_ATTENDED), (self.fay, NOT_ATTENDED),
                                (self.ann, ATTENDED), (self.cat, ATTENDED)):
            guest.refresh_from_db()
            self.assertEqual(guest.meta['attendance_status'], expected)
        self.eve.refresh_from_db()
        self.assertEqual(self.eve.meta['pd_hour'], 0)

    def test_unmarked_scope_only_with_not_attended(self):
        from .views.event import mark_attendance
        self._post(mark_attendance, self.event.id, attendance_status='attended', scope='unmarked')
        self.eve.refresh_from_db()
        self.assertEqual(self.eve.meta['attendance_status'], UNMARKED)

    def test_mark_one_row(self):
        from .views.event import mark_attendance
        self._post(mark_attendance, self.event.id, attendee=str(self.eve.id),
                   attendance_status='attended')
        self.eve.refresh_from_db()
        self.assertEqual(self.eve.meta['attendance_status'], ATTENDED)

    def test_send_letters_owed_skips_sent_and_absent(self):
        from .views.event import email_pd_letter
        with mock.patch.object(EventAttendee, 'send_pd_letter', autospec=True,
                               return_value=True) as send:
            resp = self._post(email_pd_letter, self.event.id, scope='owed')
        self.assertEqual([call.args[0].pk for call in send.call_args_list], [self.cat.pk])
        self.assertIn('Sent 1 letter', json.loads(resp.content)['message'])
        self.cat.refresh_from_db()
        self.assertTrue(self.cat.meta.get('pd_letter_sent_on'))


class EventListTests(_Fixture):
    def _row(self, **params):
        from .views.event import EventViewSet
        request = APIRequestFactory().get('/ce/events/api/events/', {'format': 'json', **params})
        force_authenticate(request, user=self.ce_user)
        data = EventViewSet.as_view({'get': 'list'})(request).render().data
        rows = data['results'] if isinstance(data, dict) else data
        return next(r for r in rows if r['id'] == str(self.event.id))

    def test_counts_and_status(self):
        row = self._row()
        self.assertEqual(
            (row['num_invited'], row['num_attended'], row['num_not_attended'],
             row['num_not_marked'], row['attendance_rate']), (6, 2, 2, 2, 33))
        self.assertEqual(row['attendance_status_label'], 'Needs attendance')

    def test_status_complete_and_upcoming(self):
        for guest in (self.eve, self.fay):
            guest.meta['attendance_status'] = ATTENDED
            guest.save()
        self.assertEqual(self._row()['attendance_status_label'], 'Complete')
        Event.objects.filter(pk=self.event.pk).update(
            start_time=timezone.now() + timedelta(days=3),
            end_time=timezone.now() + timedelta(days=3, hours=1))
        self.assertEqual(self._row()['attendance_status_label'], 'Upcoming')

    def test_twelve_hour_times(self):
        row = self._row()
        self.assertRegex(row['start_time'], r'^\d\d/\d\d/\d{4} \d\d:\d\d [AP]M$')

    def test_datatables_format_keeps_end_time(self):
        from .views.event import EventViewSet
        params = {'format': 'datatables', 'draw': '1', 'start': '0', 'length': '30',
                  'columns[0][data]': 'start_time', 'columns[0][name]': 'start_time',
                  'columns[0][searchable]': 'true', 'columns[0][orderable]': 'true',
                  'columns[0][search][value]': '',
                  'columns[1][data]': 'num_invited', 'columns[1][name]': 'id',
                  'columns[1][searchable]': 'false', 'columns[1][orderable]': 'false',
                  'columns[1][search][value]': '',
                  'order[0][column]': '0', 'order[0][dir]': 'desc'}
        request = APIRequestFactory().get('/ce/events/api/events/', params)
        force_authenticate(request, user=self.ce_user)
        rows = EventViewSet.as_view({'get': 'list'})(request).render().data['data']
        row = next(r for r in rows if r['id'] == str(self.event.id))
        self.assertIn('end_time', row)
        self.assertEqual(row['num_invited'], 6)

    def test_list_page_has_by_term_tab_for_ce(self):
        from .views.event import index
        html = self._get(index).content.decode()
        self.assertIn('id="records_by_term"', html)
        self.assertIn('Not Marked', html)

    def test_course_filter_does_not_inflate_counts(self):
        self.event.courses.add(self.eng, self.mth)
        self.assertEqual(self._row(course=str(self.eng.id))['num_invited'], 6)


class ByTermTests(_Fixture):
    def test_rollup_per_term(self):
        from .views.event import events_by_term
        rows = json.loads(self._get(events_by_term).content)['data']
        row = next(r for r in rows if r['term_id'] == str(self.term.id))
        self.assertEqual(
            (row['events'], row['invited'], row['attended'], row['rate'],
             row['required_missed'], row['pd_hours'], row['instructors']),
            (1, 6, 2, 33, 1, 5.5, 2))
        self.assertFalse(any(r['term_id'] == str(self.other_term.id) for r in rows))

    def test_term_breakdown(self):
        from .views.event import events_by_term_detail
        data = json.loads(self._get(events_by_term_detail, self.term.id).content)
        self.assertEqual([r['name'] for r in data['by_event_type']], [self.event_type.name])
        self.assertEqual({r['name'] for r in data['by_school']}, {'North High', 'South High'})
        self.assertEqual({r['name'] for r in data['by_course']}, {'ENG 101', 'MTH 102'})
        self.assertEqual([e['name'] for e in data['events']], ['Fall Workshop'])

    def test_required_missed_csv(self):
        from .views.event import required_missed_csv
        resp = self._get(required_missed_csv, self.term.id)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        self.assertEqual(rows[0][:3], ['Last Name', 'First Name', 'Email'])
        self.assertEqual([r[1] for r in rows[1:]], ['Bob'])

    def test_ce_only(self):
        from django.core.exceptions import PermissionDenied
        from .views.event import events_by_term, required_missed_csv
        outsider = CustomUser.objects.create_user(
            username=_u('o'), email=f'{_u("o")}@x.com', password='x')
        with self.assertRaises(PermissionDenied):
            self._get(events_by_term, user=outsider)
        with self.assertRaises(PermissionDenied):
            self._get(required_missed_csv, self.term.id, user=outsider)

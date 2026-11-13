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

    def test_garbage_and_mixed_case_values(self):
        from .services.summary import event_summary
        self.cat.meta['pd_hour'] = 'nan'
        self.cat.save()
        self.ann.meta['pd_hour'] = 'inf'
        self.ann.save()
        self.eve.meta['attendance_status'] = ' Attended '
        self.eve.meta['pd_hour'] = None
        self.eve.save()
        s = event_summary(self.event)
        self.assertEqual(s['pd_hours'], 0)
        self.assertEqual(s['attended'], 3)

    def test_faculty_rows_are_not_owed_letters(self):
        from .services.summary import event_summary
        EventAttendee.objects.create(event=self.event, type='faculty', meta={
            'id': '1', 'attendance_type': 'optional', 'attendance_status': ATTENDED})
        s = event_summary(self.event)
        self.assertEqual((s['attended'], s['letters_owed']), (3, 1))

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


    def test_send_letters_owed_skips_rows_without_a_certificate(self):
        from .views.event import email_pd_letter
        EventAttendee.objects.create(event=self.event, type='faculty', meta={
            'id': '1', 'attendance_type': 'optional', 'attendance_status': ATTENDED})
        with mock.patch.object(EventAttendee, 'send_pd_letter', autospec=True,
                               return_value=True) as send:
            self._post(email_pd_letter, self.event.id, scope='owed')
        self.assertEqual([call.args[0].pk for call in send.call_args_list], [self.cat.pk])

    def test_mixed_case_attended_still_gets_its_letter(self):
        from .views.event import email_pd_letter
        self.cat.meta['attendance_status'] = 'Attended'
        self.cat.save()
        with mock.patch.object(EventAttendee, 'send_pd_letter', autospec=True,
                               return_value=True) as send:
            self._post(email_pd_letter, self.event.id, scope='owed')
        self.assertEqual([call.args[0].pk for call in send.call_args_list], [self.cat.pk])

    def test_marking_attended_again_restores_pd_hours(self):
        from .views.event import mark_attendance
        self._post(mark_attendance, self.event.id, attendee=str(self.bob.id),
                   attendance_status='attended')
        self.bob.refresh_from_db()
        self.assertEqual(float(self.bob.meta['pd_hour']), 3.0)
        # Hours CE typed for someone already attended are kept.
        self.cat.meta['pd_hour'] = '1.5'
        self.cat.save()
        self._post(mark_attendance, self.event.id, attendee=str(self.cat.id),
                   attendance_status='attended')
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.meta['pd_hour'], '1.5')


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

    def test_datatables_search_and_order_with_count_columns(self):
        from .views.event import EventViewSet
        cols = [('name', 'name', 'true', 'true'), ('start_time', 'start_time', 'true', 'true'),
                ('pd_hour', 'pd_hour', 'false', 'true'),
                ('num_invited', 'id', 'false', 'false'),
                ('attendance_status_label', 'id', 'false', 'false')]
        params = {'format': 'datatables', 'draw': '1', 'start': '0', 'length': '30',
                  'search[value]': 'Fall', 'order[0][column]': '2', 'order[0][dir]': 'asc'}
        for i, (data, name, searchable, orderable) in enumerate(cols):
            params.update({f'columns[{i}][data]': data, f'columns[{i}][name]': name,
                           f'columns[{i}][searchable]': searchable,
                           f'columns[{i}][orderable]': orderable,
                           f'columns[{i}][search][value]': ''})
        request = APIRequestFactory().get('/ce/events/api/events/', params)
        force_authenticate(request, user=self.ce_user)
        response = EventViewSet.as_view({'get': 'list'})(request).render()
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.event.id), [r['id'] for r in response.data['data']])

    def test_mixed_case_status_counts_in_the_list(self):
        self.eve.meta['attendance_status'] = 'Attended'
        self.eve.save()
        self.assertEqual(self._row()['num_attended'], 3)

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

    def test_csv_neutralises_formulas(self):
        from .views.event import required_missed_csv
        user = self.bob.course_certificate.teacher_highschool.teacher.user
        user.last_name = '=HYPERLINK("http://x")'
        user.save()
        rows = list(csv.reader(io.StringIO(
            self._get(required_missed_csv, self.term.id).content.decode())))
        self.assertEqual(rows[1][0], "'=HYPERLINK(\"http://x\")")

    def test_by_term_query_count_does_not_grow_with_guests(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .views.event import events_by_term
        with CaptureQueriesContext(connection) as before:
            self._get(events_by_term)
        for i in range(5):
            EventAttendee.objects.create(event=self.event, type='highschool', meta={
                'id': str(i), 'attendance_type': 'optional', 'attendance_status': ATTENDED})
        with CaptureQueriesContext(connection) as after:
            self._get(events_by_term)
        self.assertEqual(len(after), len(before))

    def test_ce_only(self):
        from django.core.exceptions import PermissionDenied
        from .views.event import events_by_term, required_missed_csv
        outsider = CustomUser.objects.create_user(
            username=_u('o'), email=f'{_u("o")}@x.com', password='x')
        with self.assertRaises(PermissionDenied):
            self._get(events_by_term, user=outsider)
        with self.assertRaises(PermissionDenied):
            self._get(required_missed_csv, self.term.id, user=outsider)


class GetInfoTests(_Fixture):
    """#18: instructor rows store the certificate id in meta['id']."""

    def test_instructor_info_comes_from_the_certificate(self):
        info = self.ann.get_info()
        self.assertEqual((info['first_name'], info['last_name']), ('Ann', 'Teacher'))
        self.assertEqual(info['attendee'], self.ann.course_certificate.teacher_highschool.teacher)

    def test_sign_in_sheet_lists_names(self):
        html = self.event.guest_list_html
        for first in ('Ann', 'Bob', 'Cat'):
            self.assertIn(f'Teacher, {first}', html)
        self.assertNotIn('>-<', html.replace(' ', ''))

    def test_missing_record_still_falls_back(self):
        orphan = EventAttendee.objects.create(event=self.event, type='faculty', meta={
            'id': str(uuid.uuid4()), 'attendance_type': 'optional', 'attendance_status': 'N/A'})
        self.assertEqual(orphan.get_info()['first_name'], '-')


class DetailsOverviewTests(_Fixture):
    """#13: Details is a read-only overview; Edit opens the form."""

    def _page(self, method='get', **data):
        from .views.event import detail
        request = getattr(RequestFactory(), method)('/x', data)
        request.user = self.ce_user
        request._messages = mock.MagicMock()
        return detail(request, self.event.id).content.decode()

    def test_overview_shows_the_event_and_hides_the_form(self):
        self.event.description = 'Line one\nLine <b>two</b>'
        self.event.courses.add(self.eng)
        self.event.save()
        html = self._page()
        overview = html[html.index('id="event_overview"'):html.index('id="event_edit_form"')]
        for text in ('Fall Workshop', 'Online', 'Fall 2026', 'ENG 101', 'Line one<br>Line &lt;b&gt;two&lt;/b&gt;'):
            self.assertIn(text, overview)
        self.assertIn('id="btn_edit_event"', overview)
        self.assertRegex(html, r'id="event_edit_form"[^>]*class="[^"]*d-none')

    def test_invalid_edit_reopens_the_form(self):
        html = self._page('post', action='edit_event', name='')
        self.assertNotRegex(html, r'id="event_edit_form"[^>]*class="[^"]*d-none')
        self.assertRegex(html, r'id="event_overview"[^>]*class="[^"]*d-none')


class PriorYearTests(_Fixture):
    """#17: By Term rows carry the same term a year earlier."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from cis.models.term import AcademicYear
        cls.term.academic_year.name = '2026-2027'
        cls.term.academic_year.save()
        cls.last_ay = AcademicYear.objects.create(name='2025-2026')
        older_ay = AcademicYear.objects.create(name='2024-2025')
        cls.last_term = Term.objects.create(academic_year=cls.last_ay, code=cls.term.code,
                                            label='Fall 2025')
        Term.objects.create(academic_year=older_ay, code=cls.term.code, label='Fall 2024')
        last = Event.objects.create(name='Last Fall', event_type=cls.event_type,
                                    term=cls.last_term, created_by=cls.ce_user, pd_hour=2)
        for i, status in enumerate((ATTENDED, NOT_ATTENDED, NOT_ATTENDED, NOT_ATTENDED)):
            EventAttendee.objects.create(event=last, type='highschool', meta={
                'id': str(i), 'attendance_type': 'required', 'attendance_status': status})

    def _rows(self):
        from .views.event import events_by_term
        return {r['term_id']: r for r in json.loads(self._get(events_by_term).content)['data']}

    def test_row_has_the_previous_academic_years_term(self):
        prior = self._rows()[str(self.term.id)]['prior']
        self.assertEqual(prior['term'], 'Fall 2025')
        self.assertEqual((prior['events'], prior['invited'], prior['attended'], prior['rate'],
                          prior['required_missed']), (1, 4, 1, 25, 3))

    def test_prior_term_without_events_is_none(self):
        # Fall 2024 exists but has no events: nothing to compare.
        self.assertIsNone(self._rows()[str(self.last_term.id)]['prior'])


class GuestSearchTests(_Fixture):
    """#11: search guests by term taught, school or district, without courses."""

    def _search(self, **params):
        from .views.event import search_guest_list
        params.setdefault('instructor_course_status', ['Teaching'])
        request = RequestFactory().get('/x', {'attendee_type': 'instructor', **params})
        request.user = self.ce_user
        data = json.loads(search_guest_list(request).content)
        return data, {r['name'].split(',')[1].strip() + ' ' + r['col_3'] for r in data['data']}

    def test_teaching_in_a_term_matches_the_course_taught(self):
        from cis.models.section import ClassSection
        dan_teacher = self.dan.course_certificate.teacher_highschool.teacher
        ClassSection.objects.create(class_number=_u('CN'), section_number='01', term=self.term,
                                    course=self.mth, highschool=self.south, status='A',
                                    teacher=dan_teacher)
        # Dan also holds an ENG certificate he does not teach this term.
        TeacherCourseCertificate.objects.create(
            teacher_highschool=self.dan.course_certificate.teacher_highschool, course=self.eng)
        _, found = self._search(teaching_term=str(self.term.id))
        self.assertEqual(found, {'Dan MTH 102'})

    def test_by_high_school(self):
        _, found = self._search(highschool=[str(self.north.id)])
        self.assertEqual(found, {'Ann ENG 101', 'Bob ENG 101', 'Fay MTH 102'})

    def test_by_district(self):
        from cis.models.district import District
        district = District.objects.create(name=_u('District'))
        self.south.district = district
        self.south.save()
        _, found = self._search(district=[str(district.id)])
        self.assertEqual(found, {'Cat ENG 101', 'Dan MTH 102', 'Eve MTH 102'})

    def test_filters_combine(self):
        _, found = self._search(highschool=[str(self.north.id)], course=[str(self.mth.id)])
        self.assertEqual(found, {'Fay MTH 102'})

    def test_status_matches_any_case(self):
        TeacherCourseCertificate.objects.filter(pk=self.fay.course_certificate.pk).update(status='TEACHING')
        _, found = self._search(highschool=[str(self.north.id)], course=[str(self.mth.id)],
                                instructor_course_status=['teaching'])
        self.assertEqual(found, {'Fay MTH 102'})

    def test_no_filter_is_refused(self):
        data, found = self._search()
        self.assertEqual(found, set())
        self.assertIn('Choose', data['message'])

    def test_form_works_for_an_event_without_courses(self):
        from .forms import EventAttendeeFilterForm
        form = EventAttendeeFilterForm(event=self.event)
        self.assertFalse(form.fields['course'].required)
        self.assertEqual(form.fields['teaching_term'].initial, self.term.id)
        for name in ('highschool', 'district'):
            self.assertIn(name, form.fields)
        self.assertIn('Teaching', form.fields['instructor_course_status'].initial)
        self.assertNotIn('Inactive', form.fields['instructor_course_status'].initial)


class OtherGuestTypesTests(_Fixture):
    """#12: high school personnel, faculty and cohort participants as guests."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from cis.models.faculty import FacultyCoordinator
        from cis.models.course import CourseAdministrator
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition, HSPosition)
        for name in ('highschool_admin', 'faculty'):
            Group.objects.get_or_create(name=name)

        def user(first):
            return CustomUser.objects.create_user(
                username=_u(first), email=f'{first.lower()}-{_u("e")}@x.com', password='x',
                first_name=first, last_name='Staff')

        cls.counselor_user = user('Cora')
        cls.hsadmin = HSAdministrator.objects.create(user=cls.counselor_user)
        HSAdministratorPosition.objects.create(
            hsadmin=cls.hsadmin, highschool=cls.north,
            position=HSPosition.objects.create(name=_u('Counselor')), status='Active')
        retired = HSAdministrator.objects.create(user=user('Rita'))
        HSAdministratorPosition.objects.create(
            hsadmin=retired, highschool=cls.north,
            position=HSPosition.objects.create(name=_u('Principal')), status='Inactive')

        cls.liaison_user = user('Liam')
        cls.liaison = FacultyCoordinator.objects.create(user=cls.liaison_user)
        CourseAdministrator.objects.create(course=cls.eng, user=cls.liaison_user)

    def _search(self, **params):
        from .views.event import search_guest_list
        request = RequestFactory().get('/x', params)
        request.user = self.ce_user
        return json.loads(search_guest_list(request).content)['data']

    def _add(self, attendee_type, record_id):
        from .views.event import add_attendee
        return self._post(add_attendee, self.event.id, attendee=str(record_id),
                          attendance_type='required', type=attendee_type)

    def test_search_high_school_personnel_by_school(self):
        rows = self._search(attendee_type='highschool_admin', highschool=[str(self.north.id)])
        self.assertEqual([(r['id'], r['name']) for r in rows],
                         [(str(self.hsadmin.id), 'Staff, Cora')])
        self.assertIn('North High', rows[0]['col_2'])

    def test_search_faculty_by_course(self):
        rows = self._search(attendee_type='faculty', course=[str(self.eng.id)])
        self.assertEqual([r['id'] for r in rows], [str(self.liaison.id)])

    def test_add_personnel_once(self):
        self._add('highschool_admin', self.hsadmin.id)
        self._add('highschool_admin', self.hsadmin.id)
        rows = EventAttendee.objects.filter(event=self.event, type='highschool_admin')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].meta['id'], str(self.hsadmin.id))
        self.assertEqual(float(rows[0].meta['pd_hour']), 3.0)

    def test_unknown_type_is_refused(self):
        resp = self._add('superuser', self.hsadmin.id)
        self.assertEqual(json.loads(resp.content)['status'], 'error')
        self.assertFalse(EventAttendee.objects.filter(event=self.event, type='superuser').exists())

    def test_feed_and_info_name_personnel(self):
        from .views.event import attendees
        self._add('highschool_admin', self.hsadmin.id)
        row = EventAttendee.objects.get(event=self.event, type='highschool_admin')
        self.assertEqual(row.get_info()['first_name'], 'Cora')
        feed = json.loads(self._get(attendees, self.event.id).content)['data']
        mine = [r for r in feed if r['attendee_type_key'] == 'highschool_admin']
        self.assertEqual(mine[0]['name'], 'Staff, Cora')
        self.assertEqual(mine[0]['attendee_type'], 'High School Personnel')

    def test_pd_letter_goes_to_faculty(self):
        self._add('faculty', self.liaison.id)
        row = EventAttendee.objects.get(event=self.event, type='faculty')
        row.meta['attendance_status'] = ATTENDED
        row.save()
        with mock.patch('pd_event.pd_event.models.send_html_mail') as send:
            self.assertTrue(row.send_pd_letter())
        self.assertEqual(send.call_args.args[4] if len(send.call_args.args) > 4
                         else send.call_args.kwargs.get('recipient_list'),
                         [self.liaison_user.email])

    def test_letters_owed_include_personnel_and_faculty(self):
        from .services.summary import event_summary
        for kind, rid in (('faculty', self.liaison.id), ('highschool_admin', self.hsadmin.id)):
            self._add(kind, rid)
        for row in EventAttendee.objects.filter(event=self.event, type__in=['faculty', 'highschool_admin']):
            row.meta['attendance_status'] = ATTENDED
            row.save()
        self.assertEqual(event_summary(self.event)['letters_owed'], 3)  # Cat + the two

    def test_pd_letter_pdf_for_personnel(self):
        from .views.event import pd_letter
        self._add('highschool_admin', self.hsadmin.id)
        row = EventAttendee.objects.get(event=self.event, type='highschool_admin')
        with mock.patch('pdfkit.from_string', return_value=b'%PDF') as to_pdf, \
                mock.patch('cis.settings.pd_event.pd_event.from_db',
                           return_value={'pd_template': '<p>{{attendee_first_name}} {{course}}</p>'}):
            resp = self._get(pd_letter, row.id)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<p>Cora </p>', to_pdf.call_args.args[0])

    def test_email_times_use_minutes(self):
        from .models import format_event_time
        from datetime import datetime
        self.assertEqual(format_event_time(timezone.make_aware(datetime(2026, 11, 3, 14, 5))),
                         '11/03/2026 02:05 PM')


class DuplicateInviteTests(_Fixture):
    """#10: one guest row per person."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        th = cls.ann.course_certificate.teacher_highschool
        cls.ann_mth = TeacherCourseCertificate.objects.create(teacher_highschool=th, course=cls.mth)
        cls.new_th = TeacherHighSchool.objects.create(
            teacher=Teacher.objects.create(user=CustomUser.objects.create_user(
                username=_u('gus'), email=f'{_u("gus")}@x.com', password='x',
                first_name='Gus', last_name='Teacher')),
            highschool=cls.north)
        cls.gus_eng = TeacherCourseCertificate.objects.create(teacher_highschool=cls.new_th, course=cls.eng)
        cls.gus_mth = TeacherCourseCertificate.objects.create(teacher_highschool=cls.new_th, course=cls.mth)

    def _add(self, *certs):
        from .views.event import add_attendee
        request = RequestFactory().post('/x', {
            'attendee': [str(c.certificate_id) for c in certs],
            'attendance_type': 'optional', 'type': 'instructor'})
        request.user = self.ce_user
        return json.loads(add_attendee(request, self.event.id).content)

    def _rows_for(self, th):
        return EventAttendee.objects.filter(
            event=self.event, course_certificate__teacher_highschool__teacher=th.teacher)

    def test_one_row_when_adding_two_courses_of_one_person(self):
        resp = self._add(self.gus_eng, self.gus_mth)
        rows = self._rows_for(self.new_th)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(sorted(rows[0].meta['courses']), ['ENG 101', 'MTH 102'])
        self.assertIn('1 added', resp['message'])

    def test_person_already_invited_gets_the_course_not_a_row(self):
        self._add(self.ann_mth)
        rows = self._rows_for(self.ann.course_certificate.teacher_highschool)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(sorted(rows[0].meta['courses']), ['ENG 101', 'MTH 102'])

    def _duplicate_ann(self, status=UNMARKED, kind='optional', **meta):
        return EventAttendee.objects.create(
            event=self.event, course_certificate=self.ann_mth, type='instructor',
            meta={'id': str(self.ann_mth.certificate_id), 'attendance_type': kind,
                  'attendance_status': status, 'pd_hour': 0, **meta})

    def test_summary_counts_duplicates(self):
        from .services.summary import event_summary
        self._duplicate_ann()
        self.assertEqual(event_summary(self.event)['duplicates'], 1)

    def test_merge_keeps_the_strongest_row(self):
        from .views.event import merge_duplicates
        dup = self._duplicate_ann(status=NOT_ATTENDED, kind='required', note='late')
        self.ann.meta['attendance_type'] = 'optional'
        self.ann.meta['note'] = 'front row'
        self.ann.save()
        resp = json.loads(self._post(merge_duplicates, self.event.id).content)
        self.assertEqual(resp['status'], 'success')
        self.assertIn('Merged 1', resp['message'])
        rows = self._rows_for(self.ann.course_certificate.teacher_highschool)
        self.assertEqual([r.pk for r in rows], [self.ann.pk])  # attended row kept
        kept = rows[0]
        self.assertEqual(kept.meta['attendance_status'], ATTENDED)
        self.assertEqual(kept.meta['attendance_type'], 'required')  # any required
        self.assertEqual(sorted(kept.meta['courses']), ['ENG 101', 'MTH 102'])
        self.assertEqual(kept.meta['note'], 'front row; late')
        self.assertEqual(kept.meta['pd_letter_sent_on'], '11/01/2026')
        self.assertFalse(EventAttendee.objects.filter(pk=dup.pk).exists())

    def test_merge_without_duplicates(self):
        from .views.event import merge_duplicates
        resp = json.loads(self._post(merge_duplicates, self.event.id).content)
        self.assertIn('No duplicate', resp['message'])
        self.assertEqual(EventAttendee.objects.filter(event=self.event).count(), 6)


class DuplicateDisplayTests(DuplicateInviteTests):
    """#10 on the page: the warning and per-course counts."""

    def test_warning_and_course_counts(self):
        from .views.event import event_summary_view
        from .services.summary import event_summary
        self._add(self.gus_eng, self.gus_mth)
        by_course = {r['name']: r['invited'] for r in event_summary(self.event)['by_course']}
        self.assertEqual(by_course, {'ENG 101': 4, 'MTH 102': 4})
        self.assertNotIn('Merge duplicate invites', self._get(event_summary_view, self.event.id).content.decode())
        self._duplicate_ann()
        self.assertIn('Merge duplicate invites', self._get(event_summary_view, self.event.id).content.decode())


class FollowupTests(_Fixture):
    """#16: unmarked-attendance reminders and missed-required emails."""

    BASE = {
        'remind_unmarked_attendance': True, 'unmarked_attendance_days': 1,
        'unmarked_attendance_recipients': 'pd-office@x.com',
        'email_missed_required': True,
        'missed_required_subject': 'You missed {{event_type}}',
        'missed_required_template': 'Hi {{attendee_first_name}}, make-up options for {{term}}.',
        'followup_debug_email_list': 'debug@x.com',
    }

    def _run(self, debug=False, **overrides):
        from cis.models.settings import Setting
        from .services import followups
        Setting.objects.update_or_create(key='pd_event', defaults={'value': {**self.BASE, **overrides}})
        with mock.patch.object(followups, 'send_html_mail') as send, \
                self.settings(DEBUG=debug):
            result = followups.run()
        return result, [(c.args[0], c.args[4]) for c in send.call_args_list]

    def test_unmarked_reminder_once_per_event(self):
        _, sent = self._run(email_missed_required=False)
        self.assertEqual(len(sent), 1)
        subject, to = sent[0]
        self.assertEqual(to, ['pd-office@x.com'])
        self.assertIn('attendance', subject.lower())
        _, again = self._run(email_missed_required=False)
        self.assertEqual(again, [])

    def test_no_reminder_when_all_marked_or_not_ended(self):
        for guest in (self.eve, self.fay):
            guest.meta['attendance_status'] = ATTENDED
            guest.save()
        _, sent = self._run(email_missed_required=False)
        self.assertEqual(sent, [])
        Event.objects.filter(pk=self.event.pk).update(end_time=timezone.now() + timedelta(hours=2))
        self.eve.meta['attendance_status'] = UNMARKED
        self.eve.save()
        _, sent = self._run(email_missed_required=False)
        self.assertEqual(sent, [])

    def test_reminder_defaults_to_the_event_creator(self):
        _, sent = self._run(email_missed_required=False, unmarked_attendance_recipients='')
        self.assertEqual(sent[0][1], [self.ce_user.email])

    def test_missed_required_email_once(self):
        _, sent = self._run(remind_unmarked_attendance=False)
        bob_email = self.bob.course_certificate.teacher_highschool.teacher.user.email
        self.assertEqual(sent, [(f'You missed {self.event_type.name}', [bob_email])])
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.meta.get('missed_required_emailed_on'))
        _, again = self._run(remind_unmarked_attendance=False)
        self.assertEqual(again, [])

    def test_off_sends_nothing(self):
        _, sent = self._run(remind_unmarked_attendance=False, email_missed_required=False)
        self.assertEqual(sent, [])

    def test_debug_goes_to_the_debug_list_only(self):
        _, sent = self._run(debug=True)
        self.assertTrue(sent)
        self.assertTrue(all(to == ['debug@x.com'] for _, to in sent))
        _, none = self._run(debug=True, followup_debug_email_list='')
        self.assertEqual(none, [])

    def test_old_events_are_left_alone(self):
        Event.objects.filter(pk=self.event.pk).update(
            start_time=timezone.now() - timedelta(days=90),
            end_time=timezone.now() - timedelta(days=90))
        _, sent = self._run()
        self.assertEqual(sent, [])

    def test_dry_run_sends_and_saves_nothing(self):
        from cis.models.settings import Setting
        from .services import followups
        Setting.objects.update_or_create(key='pd_event', defaults={'value': self.BASE})
        with mock.patch.object(followups, 'send_html_mail') as send:
            summary, log = followups.run(dry_run=True)
        send.assert_not_called()
        self.bob.refresh_from_db()
        self.assertNotIn('missed_required_emailed_on', self.bob.meta)
        self.assertEqual(len(log['missed_required']), 1)

    def test_saving_settings_schedules_the_command(self):
        from cis.models.crontab import CronTab
        from .settings.pd_event import pd_event as form_class
        request = RequestFactory().get('/x')
        request.user = self.ce_user
        form = form_class(request, data={
            'pd_email_subject': 'Your PD letter', 'pd_template': '<p>x</p>',
            'pd_email_template': '<p>x</p>', 'event_signin_template': '<p>x</p>',
            'remind_unmarked_attendance': 'on', 'unmarked_attendance_days': '2',
            'followup_cron': '0 7 * * *'})
        self.assertTrue(form.is_valid(), form.errors)
        value = form._to_python()
        self.assertTrue(value['remind_unmarked_attendance'])
        self.assertEqual(CronTab.objects.get(command='pd_event_followups').cron, '0 7 * * *')


class FollowupCommandTests(FollowupTests):
    def test_command_dry_run(self):
        from django.core.management import call_command
        from cis.models.settings import Setting
        from .services import followups
        Setting.objects.update_or_create(key='pd_event', defaults={'value': self.BASE})
        out = io.StringIO()
        with mock.patch.object(followups, 'send_html_mail') as send:
            call_command('pd_event_followups', '--dry-run', stdout=out)
        send.assert_not_called()
        self.assertIn('Would send: 1 event(s)', out.getvalue())
        self.assertIn('missed required: Bob Teacher', out.getvalue())


class PdOnOtherPagesTests(_Fixture):
    """#15: instructor PD history, HS admin attendance, dashboards."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition, HSPosition)
        Group.objects.get_or_create(name='highschool_admin')
        cls.hs_user = CustomUser.objects.create_user(
            username=_u('hsa'), email=f'{_u("hsa")}@x.com', password='x')
        cls.hs_user.groups.add(Group.objects.get(name='highschool_admin'))
        HSAdministratorPosition.objects.create(
            hsadmin=HSAdministrator.objects.create(user=cls.hs_user), highschool=cls.north,
            position=HSPosition.objects.create(name=_u('Counselor')), status='Active')

    def test_teacher_history(self):
        from .services.summary import teacher_history
        teacher = self.bob.course_certificate.teacher_highschool.teacher
        history = teacher_history(teacher)
        self.assertEqual([r['event'] for r in history['rows']], ['Fall Workshop'])
        self.assertTrue(history['rows'][0]['required_missed'])
        term = history['terms'][0]
        self.assertEqual((term['term'], term['events'], term['attended'], term['required_missed'],
                          term['pd_hours']), ('Fall 2026', 1, 0, 1, 0))

    def test_teacher_tab_is_registered(self):
        from myce.component_registry.teacher import teacher_tabs
        from . import tabs  # noqa: F401
        self.assertIn('pd_events', teacher_tabs._tabs)

    def test_teacher_tab_renders(self):
        from django.template.loader import render_to_string
        from .tabs import teacher_pd_tab
        teacher = self.ann.course_certificate.teacher_highschool.teacher
        context = teacher_pd_tab(RequestFactory().get('/x'), teacher)
        html = render_to_string('pd_event/tabs/_teacher_pd.html', context)
        self.assertIn('Fall Workshop', html)
        self.assertIn('Attended', html)

    def test_hs_admin_page_shows_only_own_schools(self):
        from .views.highschool_admin import events
        html = self._get(events, user=self.hs_user).content.decode()
        for first in ('Ann', 'Bob', 'Fay'):
            self.assertIn(f'Teacher, {first}', html)
        for first in ('Cat', 'Dan', 'Eve'):
            self.assertNotIn(f'Teacher, {first}', html)

    def test_hs_admin_page_refuses_others(self):
        from django.core.exceptions import PermissionDenied
        from .views.highschool_admin import events
        with self.assertRaises(PermissionDenied):
            self._get(events)  # the CE user

    def test_ce_dashboard_message(self):
        from .page_messages import ce_dashboard
        messages = ce_dashboard(RequestFactory().get('/x'))
        self.assertTrue(any('need attendance marked' in m.text for m in messages))

    def test_hs_admin_dashboard_message(self):
        from .page_messages import hs_admin_dashboard
        request = RequestFactory().get('/x')
        request.user = self.hs_user
        messages = hs_admin_dashboard(request)
        self.assertEqual(len(messages), 1)
        self.assertIn('1 teacher', messages[0].text)

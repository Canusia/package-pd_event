from datetime import timedelta

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cis.models import (
    CustomUser, Term, HighSchool,
    Teacher, TeacherHighSchool, TeacherCourseCertificate,
)
from cis.models.course import Course, Cohort
from cis.models.term import AcademicYear
from pd_event.models import Event, EventType, EventAttendee


class InstructorEventListTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        cls._post_login = post_login
        user_logged_in.disconnect(cls._post_login)

    @classmethod
    def tearDownClass(cls):
        from django.contrib.auth.signals import user_logged_in
        user_logged_in.connect(cls._post_login)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')

        cls.user = CustomUser.objects.create_user(
            username='teach@example.com', email='teach@example.com', password='x',
            first_name='T', last_name='One',
        )
        cls.user.groups.add(Group.objects.get(name='instructor'))
        cls.teacher = Teacher.objects.create(user=cls.user)

        cls.other_user = CustomUser.objects.create_user(
            username='other@example.com', email='other@example.com', password='x',
            first_name='O', last_name='Two',
        )
        cls.other_user.groups.add(Group.objects.get(name='instructor'))
        cls.other_teacher = Teacher.objects.create(user=cls.other_user)

        cls.hs = HighSchool.objects.create(name='HS', code='HS1')
        cls.cohort = Cohort.objects.create(designator='ENG', name='English')
        cls.course = Course.objects.create(
            cohort=cls.cohort, catalog_number='101', title='Comp I',
            name='ENG 101', credit_hours=3, status='Active',
        )
        cls.academic_year = AcademicYear.objects.create(name='2026-2027')
        cls.term = Term.objects.create(
            academic_year=cls.academic_year, code='F26', label='Fall 2026',
        )

        cls.th = TeacherHighSchool.objects.create(teacher=cls.teacher, highschool=cls.hs)
        cls.cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=cls.th, course=cls.course,
        )
        cls.other_th = TeacherHighSchool.objects.create(
            teacher=cls.other_teacher, highschool=cls.hs,
        )
        cls.other_cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=cls.other_th, course=cls.course,
        )

        cls.event_type = EventType.objects.create(name='Workshop')
        now = timezone.now()
        cls.event = Event.objects.create(
            event_type=cls.event_type, term=cls.term,
            name='Mine', start_time=now, end_time=now + timedelta(hours=1),
            created_by=cls.user,
        )
        cls.other_event = Event.objects.create(
            event_type=cls.event_type, term=cls.term,
            name='Theirs', start_time=now, end_time=now + timedelta(hours=1),
            created_by=cls.other_user,
        )

        cls.my_attendee = EventAttendee.objects.create(
            event=cls.event, course_certificate=cls.cert, type='instructor',
            meta={'attendance_status': 'attended'},
        )
        cls.other_attendee = EventAttendee.objects.create(
            event=cls.other_event, course_certificate=cls.other_cert, type='instructor',
            meta={'attendance_status': 'attended'},
        )

    def _list(self):
        url = reverse('pd_event_instructor:attendees-list')
        resp = self.client.get(url, HTTP_ACCEPT='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        return body['results'] if isinstance(body, dict) and 'results' in body else body

    def test_viewset_returns_only_current_instructors_attendees(self):
        self.client.force_login(self.user)
        results = self._list()
        names = [row['event']['name'] for row in results]
        self.assertIn('Mine', names)
        self.assertNotIn('Theirs', names)

    def test_pd_letter_url_only_for_attended(self):
        now = timezone.now()
        evt2 = Event.objects.create(
            event_type=self.event_type, term=self.term,
            name='Skipped', start_time=now, end_time=now + timedelta(hours=1),
            created_by=self.user,
        )
        skipped = EventAttendee.objects.create(
            event=evt2, course_certificate=self.cert, type='instructor',
            meta={'attendance_status': 'not attended'},
        )

        self.client.force_login(self.user)
        results = self._list()
        by_id = {row['id']: row for row in results}

        self.assertIsNotNone(by_id[str(self.my_attendee.id)]['pd_letter_url'])
        self.assertIn(
            f'/pd_letter/{self.my_attendee.id}',
            by_id[str(self.my_attendee.id)]['pd_letter_url'],
        )
        self.assertIsNone(by_id[str(skipped.id)]['pd_letter_url'])

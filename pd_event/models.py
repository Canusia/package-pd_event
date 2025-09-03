# users/models.py
import uuid
import csv
from django.http import HttpResponse

from django.utils import timezone
from django.db import models

from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models import JSONField
from django.core.mail import EmailMessage, send_mail
from django.template.loader import render_to_string
from django.urls import reverse_lazy

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template, render_to_string

# from mailer import send_mail, send_html_mail

from cis.settings.pd_event import pd_event
from cis.utils import export_to_excel, event_file_upload_path, getDomain
from cis.storage_backend import PrivateMediaStorage


COLLEGE_COURSE_OPTIONS = (
    ('1', 'Advanced Placement (AP)'),
    ('2', 'International Baccalaureate (IB)'),
    ('3', 'Community College'),
    ('4', 'Another 4 year Institution'),
    ('5', 'Other'),
)

class EventType(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name']

class Venue(models.Model):
    """
    Venue model to store event location details
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.name}, {self.city}, {self.state}"

    class Meta:
        ordering = ['name']

class Event(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )
    venue = models.ForeignKey('pd_event.Venue', on_delete=models.PROTECT, null=True, blank=True)

    courses = models.ManyToManyField('cis.Course')

    start_time = models.DateTimeField(
        verbose_name="Start Date & Time",
        blank=True,
        null=True
    )

    end_time = models.DateTimeField(verbose_name="End Date & Time",
        blank=True,
        null=True
    )

    event_type = models.ForeignKey(
        'pd_event.EventType',
        on_delete=models.PROTECT,
        verbose_name='Event Type'
    )
    
    term = models.ForeignKey("cis.Term", on_delete=models.PROTECT)

    created_on = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    description = models.TextField(
        blank=True,
        null=True
    )

    pd_hour = models.FloatField(
        default=0.0,
        verbose_name='PD Hour(s)',
        null=True,
    )
    
    cost_per_attendee = models.FloatField(
        default=0.0,
        verbose_name='Cost Per Attendee',
        null=True,
    )

    DELIVERY_OPTIONS = [
        ('', 'Select'),
        ('In Person', 'In Person'),
        ('Online', 'Online'),
        ('Hybrid', 'Hybrid'),
    ]
    delivery_mode = models.CharField(
        max_length=10,
        verbose_name='Delivery Mode',
        choices=DELIVERY_OPTIONS,
        blank=True,
        null=True
    )

    cohort = JSONField(
        blank=True,
        null=True,
        verbose_name='Subject(s)'
    )

    meta = JSONField(
        default=dict,
        blank=True,
        null=True
    )

    @property
    def sexy_courses(self):
        courses = ','.join([course.title for course in self.courses.all()])
        return courses
    
    def __str__(self):
        
        # courses = ','.join([course.title for course in self.courses.all()])

        return f"{self.term.label} - {self.event_type.name} - ({self.name})"
    
    def add_note(self, createdby=None, note='', meta=None):

        if not createdby:
            from cis.models.customuser import CustomUser
            createdby = CustomUser.objects.get(
                username='cron'
            )

        from cis.models.note import EventNote
        note = EventNote(
            createdby=createdby,
            note=note,
            event=self
        )

        if not meta:
            meta = {'type': 'private'}

        note.meta = meta
        note.save()

        return note

    @property
    def ce_url(self):
        return reverse_lazy('pd_event:event', kwargs={
            'record_id': self.id
        })
    
    @property
    def faculty_url(self):
        return reverse_lazy('pd_event_faculty:event', kwargs={
            'record_id': self.id
        })
    
    @property
    def start_time_local(self):
        return timezone.localtime(self.start_time)

    @property
    def end_time_local(self):
        return timezone.localtime(self.end_time)

    @property
    def guest_list_html(self):
        attendees = EventAttendee.objects.filter(
            event=self
        )

        records = []
        for attendee in attendees:
            # a = attendee.get_info()

            try:
                records.append(
                    attendee.course_certificate.teacher_highschool.teacher.user.last_name + ', ' + attendee.course_certificate.teacher_highschool.teacher.user.first_name
                )
            except AttributeError:
                pass

        records.sort()

        return render_to_string(
            'pd_event/event-attendee-list.html', {
                'attendees': records
            })

    @property
    def course_list(self):
        return [course.name for course in self.courses.all().order_by('name')]
    
    @property
    def cohorts(self):
        if self.cohort:
            from cis.models.course import Cohort
            cohorts = Cohort.objects.filter(
                id__in=self.cohort
            ).order_by('name')

            return ','.join(cohort.name for cohort in cohorts)
        return '-'

    def files(self):
        return EventFile.objects.filter(
            event=self
        )

    @property
    def num_guests(self):
        return EventAttendee.objects.filter(
            event=self
        ).count()

    @property
    def marked_as_attended(self):
        return EventAttendee.objects.filter(
            event=self,
            meta__attendance_status='attended'
        )

    @property
    def marked_as_not_attended(self):
        return EventAttendee.objects.filter(
            event=self,
            meta__attendance_status='not attended'
        )

    @property
    def event_guests(self):
        return EventAttendee.objects.filter(
            event=self
        )

    @property
    def num_attendees(self):
        return EventAttendee.objects.filter(
            event=self,
            meta__attendance_status='attended'
        ).count()

    @property
    def num_not_attended(self):
        return EventAttendee.objects.filter(
            event=self,
            meta__attendance_status='not attended'
        ).count()

    @property
    def num_attachments(self):
        return EventFile.objects.filter(
            event=self
        ).count()

    def send_reminder_email(self):
        pd_settings = pd_event.from_db()

        subject = pd_settings.get('event_reminder_subject', '')
        
        attendees = EventAttendee.objects.filter(
            event=self
        )

        for attendee in attendees:
            message = pd_settings.get('event_reminder_template', '')

            to = []
            a = attendee.get_info()
            message = message.format(
                attendee_first_name=attendee.course_certificate.teacher_highschool.teacher.user.first_name,
                attendee_last_name=attendee.course_certificate.teacher_highschool.teacher.user.last_name,
                course=attendee.course_certificate.course.name,
                term=str(self.term),
                start_date_time=self.start_time_local.strftime('%m/%d/%Y %I:%m %p'),
                end_date_time=self.end_time_local.strftime('%m/%d/%Y %I:%m %p'),
                event_type=self.event_type,
                description=self.description
            )

            if getattr(settings, 'DEBUG') == True:
                to = [
                    'kadaji@gmail.com'
                ]
            else:
                to.append(attendee.course_certificate.teacher_highschool.teacher.user.email)
                if attendee.course_certificate.teacher_highschool.teacher.user.alt_email:
                    to.append(attendee.course_certificate.teacher_highschool.teacher.user.alt_email)
                if attendee.course_certificate.teacher_highschool.teacher.user.secondary_email:
                    to.append(attendee.course_certificate.teacher_highschool.teacher.user.secondary_email)
                    
            template = get_template('cis/email.html')
            html_body = template.render({
                'message': message
            })
        
            send_html_mail(
                subject,
                message,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            return True

class EventFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    description = models.TextField(blank=True, null=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=event_file_upload_path
    )

    event = models.ForeignKey(
        'pd_event.Event',
        on_delete=models.PROTECT
    )

    uploaded_on = models.DateTimeField(auto_now=True)

class EventAttendee(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        'pd_event.Event',
        on_delete=models.CASCADE
    )

    course_certificate = models.ForeignKey(
        'cis.TeacherCourseCertificate',
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )

    ATTENDEE_TYPE = [
        ('instructor', 'Instructor'),
        # ('highschool_admin', 'High School Personnel'),
        # ('cohort_participant', 'Cohort Participant'),
        ('highschool', 'High School'),
        ('faculty', 'Faculty'),
    ]
    type = models.CharField(
        choices=ATTENDEE_TYPE,
        max_length=50,
        default='instructor'
    )
    
    meta = JSONField(
        blank=True,
        null=True
    )

    class Meta:
        unique_together = [
            ('event', 'meta')
        ]

    def send_pd_letter(self):
        pd_settings = pd_event.from_db()

        subject = pd_settings.get('pd_email_subject', '')
        message = pd_settings.get('pd_email_template', '')

        message = Template(message)
        context = Context({
            'attendee_first_name' : self.course_certificate.teacher_highschool.teacher.user.first_name,
            'attendee_last_name' : self.course_certificate.teacher_highschool.teacher.user.last_name,
            'course' : self.course_certificate.course.name,
            'term' : str(self.event.term),
            'earned_pd_hour' : self.meta.get('pd_hour'),
            'start_date_time' : self.event.start_time_local.strftime('%m/%d/%Y %I:%m %p'),
            'end_date_time' : self.event.end_time_local.strftime('%m/%d/%Y %I:%m %p'),
            "event_type" : self.event.event_type,
            'pd_note' : self.meta.get('note'),
            'delivery_mode' : self.event.delivery_mode,
            'pd_letter_url' : self.pd_url,
            'description' : self.event.description
        })
        text_body = message.render(context)

        if self.type == 'highschool':
            return False

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        to = [
            self.course_certificate.teacher_highschool.teacher.user.email
        ]
        if self.course_certificate.teacher_highschool.teacher.user.alt_email:
            to.append(self.course_certificate.teacher_highschool.teacher.user.alt_email)
        if self.course_certificate.teacher_highschool.teacher.user.secondary_email:
            to.append(self.course_certificate.teacher_highschool.teacher.user.secondary_email)

        if getattr(settings, 'DEBUG') == True:
            to = ['kadaji@gmail.com']
        
        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )
        return True

    @property
    def pd_url(self):
        return getDomain() + str(reverse_lazy('pd_event:pd_letter', kwargs={
            'attendance_id': self.id}))

    def get_info(self):
        try:
            if self.type == 'instructor':
                from cis.models.teacher import Teacher
                attendee = Teacher.objects.get(
                    pk=self.meta['id']
                )
                return {
                    'first_name': attendee.user.first_name,
                    'last_name': attendee.user.last_name,
                    'email': attendee.user.email,
                    'alt_email': attendee.user.alt_email,
                    'attendee': attendee
                }
            elif self.type == 'faculty':
                from cis.models.faculty import FacultyCoordinator
                attendee = FacultyCoordinator.objects.get(
                    pk=self.meta['id']
                )
                
                return {
                    'first_name': attendee.user.first_name,
                    'last_name': attendee.user.last_name,
                    'email': attendee.user.email,
                    'attendee': attendee
                }
            elif self.type == 'cohort_participant':
                from cis.models.course import CohortParticipant
                attendee = CohortParticipant.objects.get(
                    pk=self.meta['id']
                )

                return {
                    'first_name': attendee.user.first_name,
                    'last_name': attendee.user.last_name,
                    'email': attendee.user.email,
                    'alt_email': attendee.user.secondary_email,
                    'attendee': attendee
                }
            elif self.type == 'highschool':
                from cis.models.highschool import HighSchool
                attendee = HighSchool.objects.get(
                    pk=self.meta['id']
                )
                
                return {
                    'first_name': attendee.name,
                    'attendee': attendee
                }
        except:
            return {
                'first_name': '-',
                'last_name': '-',
                'email': '',
                'alt_email': '',
                'attendee': None
            }
        

class InfoSession(models.Model):
    """
    Info Session model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )
    sessions = models.ManyToManyField(
        'Event',
        related_name='info_sessions'
    )
    description = models.TextField(
        blank=True,
        null=True
    )
    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT
    )
    created_on = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    meta = JSONField(
        default=dict,
        blank=True,
        null=True
    )
    def __str__(self):
        return f"Info Session for {self.term}"
    
    class Meta:
        ordering = ['-term__code']

    @property
    def rsvp_url(self):
        from cis.utils import getDomain
        return getDomain() + str(reverse_lazy('info_session:start_rsvp', kwargs={
            'info_session_id': self.id
        }))
    
    @property
    def ce_url(self):
        return reverse_lazy('pd_event:info_session', kwargs={
            'record_id': self.id
        })
    
class InfoSessionNote(models.Model):
    """
    Info Session Note model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    info_session = models.ForeignKey(
        'pd_event.InfoSession',
        on_delete=models.CASCADE
    )
    created_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)
    note = models.TextField()
    created_on = models.DateTimeField(auto_now=True)
    meta = JSONField(
        blank=True,
        null=True
    )
    def __str__(self):
        return f"Note for {self.info_session.term} by {self.created_by.username}"
    
class InfoSessionAttendee(models.Model):
    """
    Info Session Attendee model
    """
    created_on = models.DateTimeField(auto_now=True)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    info_session = models.ForeignKey(
        'pd_event.InfoSession',
        on_delete=models.CASCADE
    )
    meta = JSONField(
        blank=True,
        null=True
    )
    
    def send_confirmation_email(self):
        subject = self.info_session.meta.get('signup_confirmation_subject', 'Change Me')
        message = self.info_session.meta.get('signup_confirmation_message', '')

        message = Template(message)
        
        context = Context({
            'submitted_by_name' : self.submitted_by_name(),
            'info_session_location' : self.info_session_location,
            'info_session_date_time' : self.info_session_date_time,
        })
        text_body = message.render(context)

        if getattr(settings, 'DEBUG') == True:
            to = ['kadaji@gmail.com']
        else:
            to = [self.submitted_by_email()]
            # add other emails if available
            if self.attendees:
                for attendee in self.attendees():
                    if attendee.get('email'):
                        to.append(attendee.get('email'))

        from_email = settings.DEFAULT_FROM_EMAIL
        return send_mail(
            subject,
            text_body,
            from_email=from_email,
            recipient_list=to,
            fail_silently=True
        )

    @property
    def info_session_location(self):
        if self.meta and self.meta.get('session_id'):
            session = Event.objects.get(
                id=self.meta['session_id']
            )
            if session.venue:
                return f"{session.venue.name}, {session.venue.address}, {session.venue.city}, {session.venue.state} {session.venue.zip}"
        return '-'
    
    @property
    def info_session_date_time(self):
        if self.meta and self.meta.get('session_id'):
            session = Event.objects.get(
                id=self.meta['session_id']
            )
            return f"{session.start_time_local.strftime('%m/%d/%Y %I:%M %p')}"
        return '-'

    def selected_session(self):
        from .models import Event
        if self.meta and self.meta.get('session_id'):
            try:
                return Event.objects.get(
                    id=self.meta['session_id']
                ).name
            except Event.DoesNotExist:
                return None
            
    def interested_courses(self):
        if self.meta and self.meta.get('interested_courses'):
            courses = [k.get('course_name') for k in self.meta['interested_courses']]
            return courses if isinstance(courses, list) else [courses]
        return []
    
    def number_of_attendees(self):
        if self.meta and self.meta.get('attendees'):
            return len(self.meta['attendees'])
        return 0
    
    def other_college_courses(self):
        result = []

        if self.meta and self.meta.get('other_course'):
            for k, v in COLLEGE_COURSE_OPTIONS:
                if k in self.meta['other_course']:
                    result.append(v)

        if self.meta and self.meta.get('other_course'):
            result.append('Other ' + self.meta['other_course'])

        return '<br>'.join(result) if result else '-'
    
    def highschool_name(self):
        if self.meta and self.meta.get('highschool_name'):
            return self.meta['highschool_name']
        return '-'
    
    def attendees(self):
        if self.meta and self.meta.get('attendees'):
            return self.meta['attendees']
        return []
    
    def highschool_state(self):
        if self.meta and self.meta.get('highschool_state'):
            return self.meta['highschool_state']
        return '-'
    
    def submitted_by(self):
        if self.meta and self.meta.get('your_name'):
            return self.meta['your_name'] + "<br>" + self.meta.get('your_email', '') + "<br>" + self.meta.get('your_role', '')
        return '-'
    
    def submitted_by_name(self):
        if self.meta and self.meta.get('your_name'):
            return self.meta['your_name']
        return '-'
    
    def submitted_by_email(self):
        if self.meta and self.meta.get('your_email'):
            return self.meta['your_email']
        return '-'

    def can_edit(self):
        return True
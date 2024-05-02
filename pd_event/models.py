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

from mailer import send_mail, send_html_mail

from cis.settings.pd_event import pd_event
from cis.utils import export_to_excel, event_file_upload_path, getDomain
from cis.storage_backend import PrivateMediaStorage

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
    # venue = models.ForeignKey("cis.Venue", on_delete=models.PROTECT)

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
            a = attendee.get_info()
            if a.get('last_name'):
                records.append(a.get('last_name', '') + ', ' + a.get('first_name'))
            else:
                records.append(a.get('first_name'))

        records.sort()

        return render_to_string(
            'pd_event/event-attendee-list.html', {
                'attendees': records
            })

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

            a = attendee.get_info()
            message = message.format(
                attendee_first_name=a.get('first_name'),
                attendee_last_name=a.get('last_name'),
                cohort=self.cohorts,
                term=str(self.term),
                start_date_time=self.start_time_local.strftime('%m/%d/%Y %H:%m'),
                end_date_time=self.end_time_local.strftime('%m/%d/%Y %H:%m'),
                event_type=self.event_type,
                description=self.description
            )

            if getattr(settings, 'DEBUG') == True:
                email.to = [
                    'kadaji@gmail.com'
                ]
        
            template = get_template('cis/email.html')
            html_body = template.render({
                'message': body
            })
        
            send_html_mail(
                subject,
                body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                email.to
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

    ATTENDEE_TYPE = [
        ('instructor', 'Instructor'),
        # ('highschool_admin', 'High School Personnel'),
        # ('cohort_participant', 'Cohort Participant'),
        ('highschool', 'High School'),
        ('faculty', 'Faculty'),
    ]
    type = models.CharField(
        choices=ATTENDEE_TYPE,
        max_length=50
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

        attendee_info = self.get_info()

        message = Template(message)
        context = Context({
            'attendee_first_name' : attendee_info.get('first_name'),
            'attendee_last_name' : attendee_info.get('last_name'),
            'cohort' : self.event.cohorts,
            'term' : str(self.event.term),
            'earned_pd_hour' : self.meta.get('pd_hour'),
            'start_date_time' : self.event.start_time_local.strftime('%m/%d/%Y %H:%m'),
            'end_date_time' : self.event.end_time_local.strftime('%m/%d/%Y %H:%m'),
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
            attendee_info.get('email'),
            attendee_info.get('alt_email'),
            attendee_info.get('secondary_email')
        ]
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
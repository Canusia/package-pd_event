import datetime

from django import forms
from django.forms import ModelForm, ValidationError

from django.utils import timezone

from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.conf import settings

from django.utils.safestring import mark_safe
from cis.models.course import Cohort, Course
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.faculty import FacultyCoordinator
from .models import (
    EventType,
    Event,
    EventAttendee,
    EventFile
)

from form_fields import fields as FFields
from cis.validators import validate_html_short_code, validate_cron
from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from mailer import send_mail, send_html_mail

class EventEmailForm(forms.Form):

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='send_email_to_guests'
    )

    email_to = forms.ChoiceField(
        label='Send Email To',
        choices=[
            # ('to_all_guests', 'All Guests'),
            ('to_all', 'All Guests'),
            ('to_attendees', 'All Marked as Attended'),
            ('to_not_attendees', 'All Marked as Not Attended'),
        ]
    )

    short_codes = FFields.ReadOnlyField(
        required=False,
        label=mark_safe(
            '<p class="alert">Use the form to email event guests.<br><br>Customize the subject and message with the following short codes. {{event_description}}, {{event_start_date_time}}, {{event_end_date_time}}, {{event_term}}, {{attendee_first_name}}, {{attendee_last_name}}, {{courses_name}}</p>'
        ),
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    subject = forms.CharField(
        required=True,
        validators=[validate_html_short_code],
        widget=forms.TextInput(
            attrs={
                'class': 'col-8'
            }
        )
    )

    message = forms.CharField(
        widget=CKEditorWidget(
            attrs={"class": "django_ckeditor_5"}
        ),
        required=False,
        help_text='',
        validators=[validate_html_short_code]
    )

    copy_me = forms.BooleanField(
        required=False,
        label='Send Me a Copy',
        help_text='If checked, a copy of the email will be sent to your email address.',
        initial=False
    )

    def __init__(self, event, email_type='send_email_to_guests', *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = email_type

        if email_type == 'send_email_to_guests':
            del self.fields['email_to']
        else:
            self.fields['short_codes'].label = mark_safe(
                '<p class="card p-3">Customize the subject and message with the following short codes. {{event_description}}, {{event_start_date_time}}, {{event_end_date_time}}, {{event_term}}, {{attendee_first_name}}, {{attendee_last_name}}.<br><br>If sending to attendees {{pd_note}}, {{pd_letter_url}}.</p>'
            )
        
    def save(self, request, event):
        data = self.cleaned_data

        from .models import EventAttendee

        if data.get('email_to') == 'to_attendees':
            attendees = event.marked_as_attended
        elif data.get('email_to') == 'to_not_attendees':
            attendees = event.marked_as_not_attended
        else:
            attendees = event.event_guests

        to_list = []
        for attendee in attendees:

            if attendee.type == 'highschool':
                return False

            message = Template(data.get('message', ''))
            subject = Template(data.get('subject', ''))

            attendee_info = attendee.get_info()
            context = Context({
                'attendee_first_name' : attendee.course_certificate.teacher_highschool.teacher.user.first_name,
                'attendee_last_name' : attendee.course_certificate.teacher_highschool.teacher.user.last_name,
                'courses_name' : event.sexy_courses,
                'event_term' : str(event.term),
                'event_start_date_time' : event.start_time_local.strftime('%m/%d/%Y %I:%m %p'),
                'event_end_date_time' : event.end_time_local.strftime('%m/%d/%Y %I:%m %p'),
                'description' : event.description,
                'pd_letter_url' : attendee.pd_url,  
                'pd_note' : attendee.meta.get('note'),
            })

            if data.get('email_to') == 'to_attendees':
                if attendee.meta['attendance_status'] == 'attended':    
                    attendee.meta['pd_letter_sent_on'] = datetime.datetime.now().strftime('%m/%d/%Y')
                    attendee.save()

            text_body = message.render(context)
            subject = subject.render(context)

            to = [
                attendee.course_certificate.teacher_highschool.teacher.user.email
            ]

            if attendee.course_certificate.teacher_highschool.teacher.user.alt_email:
                to.append(attendee.course_certificate.teacher_highschool.teacher.user.alt_email)

            if attendee.course_certificate.teacher_highschool.teacher.user.secondary_email:
                to.append(attendee.course_certificate.teacher_highschool.teacher.user.secondary_email)

            if getattr(settings, 'DEBUG') == True:
                to = [
                    'kadaji@gmail.com'
                ]
        
            to_list += to
            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })
        
            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to,
                headers={
                    'Reply-To': request.user.email
                }
            )

        if data.get('copy_me', False):

            message = Template(data.get('message', ''))
            subject = Template(data.get('subject', ''))

            attendee_info = attendee.get_info()
            context = Context({
                # 'attendee_first_name' : attendee_info.get('first_name'),
                # 'attendee_last_name' : attendee_info.get('last_name'),
                'courses_name' : event.sexy_courses,
                'event_term' : str(event.term),
                'event_start_date_time' : event.start_time_local.strftime('%m/%d/%Y %I:%m %p'),
                'event_end_date_time' : event.end_time_local.strftime('%m/%d/%Y %I:%m %p'),
                'description' : event.description,
                # 'pd_letter_url' : attendee.pd_url,  
                # 'pd_note' : attendee.meta.get('note'),
            })

            text_body = message.render(context)
            text_body += "\n\n" + "Sent this email to " + ', '.join(to_list)
            
            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            subject = subject.render(context)

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                [request.user.email]
            )
        
        event.add_note(
            request.user,
            'Sent email<br>' + data.get('subject') + "<br>" + data.get('message') + '<br>To: ' + ','.join(to_list)
        )
        return True
    

class EventAttendeeFilterForm(forms.Form):
    
    course = forms.ModelMultipleChoiceField(
        queryset=None,
        required=True,
        label='Course(s)'
    )

    instructor_course_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        required=False,
        label='Instructor Course Status',
        widget=forms.CheckboxSelectMultiple
    )

    since = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format='%m/%d/%Y',
            attrs={
                'class': 'col-md-3 col-sm-6',
                'placeholder': 'mm/dd/yyyy'
            }
        )
    )
    
    def __init__(self, event, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['course'].queryset = event.courses.all().order_by('name')
        self.fields['course'].initial = event.courses.all()

class EventFileForm(ModelForm):
    class Meta:
        model = EventFile
        fields = '__all__'
        exclude = ['description']

        widgets = {
            'event': forms.HiddenInput()
        }
    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, event, *args, **kwargs):
        instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = 'edit_event_file'
        self.fields['event'].initial = event.id

class EventForm(ModelForm):
    courses = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='Course(s)'
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    start_time = forms.CharField(
        label='Start Date/Time',
        help_text='Eg: 10/10/2020 01:30 PM',
        widget=forms.TextInput(attrs={'class':'col-md-6 col-sm-12 datetime_picker'}),
    )

    end_time = forms.CharField(
        label='End Date/Time',
        help_text='Eg: 10/10/2020 01:30 PM',
        widget=forms.TextInput(attrs={'class':'col-md-6 col-sm-12 datetime_picker'}),
    )

    class Media:
        js = [
            'js/pd_event.js',
            'js/pd_events.js'
        ]

    def __init__(self, request, *args, **kwargs):
        instance = kwargs.get('instance')

        super().__init__(*args, **kwargs)       
        
        if instance:            
            try:
                self.fields['start_time'].initial = timezone.localtime(instance.start_time).strftime('%m/%d/%Y %I:%M %p')
                self.fields['end_time'].initial = timezone.localtime(instance.end_time).strftime('%m/%d/%Y %I:%M %p')
            except:
                ...

        from cis.utils import user_has_faculty_role
        from cis.models.faculty import FacultyCoordinator
        if request and user_has_faculty_role(request.user):
            try:
                faculty_courses = FacultyCoordinator.courses_overseeing(
                    user=request.user,
                )

                self.fields['courses'].queryset = Course.objects.filter(
                    id__in=faculty_courses.values_list('course__id', flat=True),
                    status__iexact='active'
                ).order_by('name')
            except Exception as e:
                self.fields['courses'].queryset = Course.objects.filter(
                    status__iexact='active'
                ).order_by('name')
        else:
            self.fields['courses'].queryset = Course.objects.filter(
                status__iexact='active'
            ).order_by('name')
            
        self.fields['action'].initial = 'edit_event'
        
    class Meta:
        model = Event
        fields = [
            'courses',
            'event_type',
            'term',
            'delivery_mode',
            # 'start_time',
            # 'end_time',
            'pd_hour',
            'description'
        ]
        exclude = ['created_by', 'cohort', 'name']

        labels = {
            # 'name': 'CIS Events DB ID'
        }
        help_texts = {
            # 'start_time': 'As mm/dd/yyyy hh:mm',
            # 'end_time': 'As mm/dd/yyyy hh:mm',
            'description': 'This text will appear in the PD letter.'
        }

    def clean_start_time(self):
        start_time = self.cleaned_data.get('start_time')

        try:
            start_time = datetime.datetime.strptime(start_time, '%m/%d/%Y %I:%M %p')
        except:
            raise ValidationError('Please enter a valid start time')

        return start_time

    def clean_end_time(self):
        start_time = self.cleaned_data.get('start_time')
        end_time = self.cleaned_data.get('end_time')

        try:
            end_time = datetime.datetime.strptime(end_time, '%m/%d/%Y %I:%M %p')
        except:
            raise ValidationError('Please enter a valid end time')
        
        if not end_time:
            return end_time
        
        if not start_time:
            raise ValidationError('Please enter the start date and time')

        if start_time > end_time:
            raise ValidationError('Please enter valid start and end times')
        
        return end_time

    def save(self, commit=True, request=None, *args, **kwargs):
        record = super().save(commit=False, *args, **kwargs)

        data = self.cleaned_data
        record.created_by = request.user

        record.start_time = data.get('start_time')
        record.end_time = data.get('end_time')

        record.save()

        for course in data.get('courses'):
            record.courses.add(course)

        return record

class EventTypeForm(ModelForm):
    class Meta:
        model = EventType
        fields = '__all__'

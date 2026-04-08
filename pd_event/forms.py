import datetime

from django import forms
from django.forms import ModelForm, ValidationError

from django.utils import timezone

from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.conf import settings

from django.utils.safestring import mark_safe
from cis.models.course import Cohort, Course, Location
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.faculty import FacultyCoordinator
from cis.models.term import Term
from .models import (
    EventType,
    Event,
    EventAttendee,
    EventFile,
    Venue,
    InfoSession,
    InfoSessionAttendee
)

from form_fields import fields as FFields
from cis.validators import validate_html_short_code, validate_cron
from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from cis.utils import user_has_cis_role, user_has_faculty_role
from django_recaptcha.fields import ReCaptchaField
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

            message = data.get('message', '')
            message += "<p>" + "Sent this email to " + '<br>'.join(to_list) + "</p>"

            message = Template(message)
            subject = Template(data.get('subject', ''))

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
                [request.user.email],
                headers={
                    'Reply-To': request.user.email
                }
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

    highschool_category = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label='High School Category',
        widget=forms.CheckboxSelectMultiple
    )

    skip_attendees_from = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='Skip Attendees From'
    )

    skip_guests_from = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        help_text='Use this if you want to skip guests when attendance has not been marked',
        label='Skip Guests From'
    )
    
    def __init__(self, event, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from cis.models.highschool import HighSchool
        try:
            categories = HighSchool.objects.values('category').order_by('category')

            category_choices = []
            for cat in categories:
                if ((cat['category'], cat['category']) not in category_choices):
                    category_choices.append(
                        (cat['category'], cat['category'])
                    )
        except:
            category_choices = [(   '', '--- No Categories Available ---')]
        self.fields['highschool_category'].choices = category_choices

        self.fields['course'].queryset = event.courses.all().order_by('name')
        self.fields['course'].initial = event.courses.all()

        self.fields['skip_attendees_from'].queryset = Event.objects.filter(courses__in=event.courses.all()).order_by('-start_time')

        self.fields['skip_guests_from'].queryset = Event.objects.filter(courses__in=event.courses.all()).order_by('-start_time')

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

class InfoSessionForm(ModelForm):

    page_1_intro = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
            }
        ),
        required=False,
        label='Page 1 Intro',
        help_text='This text will appear on the first page of the info session RSVP form'
    )
    page_2_intro = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
            }
        ),
        required=False,
        label='Page 2 Intro',
        help_text='This text will appear on the second page of the info session RSVP form'
    )

    signup_confirmation_subject = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    signup_confirmation_message = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
            }
        ),
        required=False,
        label='Signup Confirmation Message',
        help_text='This text will appear on the signup confirmation email. You can use the following short codes: {{info_session_date_time}}, {{info_session_location}}, {{submitted_by_name}}'
    )

    redirect_url = forms.CharField(
        widget=forms.TextInput,
        required=False,
        label='Redirect URL',
        help_text='If you want to redirect the user to a different page after submitting the form',
        initial='/'
    )

    def clean_redirect_url(self):
        redirect_url = self.cleaned_data.get('redirect_url')

        if not redirect_url or redirect_url.strip() == '':
            return redirect_url
        
        # check if this is a valid fully qualified URL
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError
        url_validator = URLValidator()
        try:
            url_validator(redirect_url)
        except ValidationError:
            raise ValidationError('Please enter a valid URL')

        return redirect_url
    
    class Meta:
        model = InfoSession
        fields = '__all__'
        exclude = ['created_by', 'meta']

        widgets = {
            # 'notes': CKEditorWidget(
            #     attrs={
            #         'class': 'django_ckeditor_5'
            #     }
            # )
        }

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['action'].initial = 'edit_info_session'
        self.fields['term'].queryset = Term.objects.all().order_by('-code')
        self.fields['sessions'].queryset = Event.objects.all().order_by('-start_time')
        self.fields['sessions'].widget.attrs.update({
            'class': 'form-control select2',
            'multiple': 'multiple'
        })

        if kwargs.get('instance'):
            instance = kwargs.get('instance')
            if instance.meta:
                self.fields['page_1_intro'].initial = instance.meta.get('page_1_intro', '')
                self.fields['page_2_intro'].initial = instance.meta.get('page_2_intro', '')
                self.fields['redirect_url'].initial = instance.meta.get('redirect_url', '/')
                self.fields['signup_confirmation_message'].initial = instance.meta.get('signup_confirmation_message', '/')
                self.fields['signup_confirmation_subject'].initial = instance.meta.get('signup_confirmation_subject', '/')

    def save(self, commit=True, request=None, *args, **kwargs):
        record = super().save(commit=False, *args, **kwargs)

        data = self.cleaned_data

        if not record.meta:
            record.meta = {}

        record.meta['page_1_intro'] = data.get('page_1_intro')
        record.meta['page_2_intro'] = data.get('page_2_intro')
        record.meta['redirect_url'] = data.get('redirect_url')

        record.meta['signup_confirmation_subject'] = data.get('signup_confirmation_subject')
        record.meta['signup_confirmation_message'] = data.get('signup_confirmation_message')

        record.created_by = request.user

        record.save()
        record.sessions.clear()

        for session in data.get('sessions'):
            record.sessions.add(session)
            
        return record

class EventReportForm(forms.Form):
    action = forms.CharField(
        widget=forms.HiddenInput
    )

    event_agenda = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 5
            }
        ),
        required=False,
        label='Event agenda',
        help_text=''
    )

    event_summary = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 5
            }
        ),
        required=False,
        label='Brief event summary',
        help_text='Describe any key moments that shaped the outcome'
    )

    event_questions = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 5
            }
        ),
        required=False,
        label='Questions/concerns that arose',
        help_text=''
    )

    event_future_changes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 5
            }
        ),
        required=False,
        label='When you run this next time, what are the 1 - 3 changes you\'d make and why?',
        help_text=''
    )

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['action'].initial = 'edit_event_report'

        self.fields['event_agenda'].initial = record.meta.get('event_agenda', '')
        self.fields['event_summary'].initial = record.meta.get('event_summary', '')
        self.fields['event_questions'].initial = record.meta.get('event_questions', '')
        self.fields['event_future_changes'].initial = record.meta.get('event_future_changes', '')

    def save(self, record, commit=True, request=None):
        data = self.cleaned_data
        
        if not record.meta:
            record.meta = {}
        record.meta['event_agenda'] = data.get('event_agenda')
        record.meta['event_summary'] = data.get('event_summary')
        record.meta['event_questions'] = data.get('event_questions')
        record.meta['event_future_changes'] = data.get('event_future_changes')

        if commit:
            record.save()
        return record
    
class EventForm(ModelForm):
    name = forms.CharField(
        label='Event Name',
        max_length=255,
        widget=forms.TextInput(attrs={'class':'col-md-6 col-sm-12'}),
    )

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

        from .settings.pd_event import pd_event as pd_event_settings
        config = pd_event_settings.from_db()

        if not config.get('track_pd_event_cost', False):
            del self.fields['cost_per_attendee']

        from cis.utils import user_has_faculty_role, user_has_cis_role
        from cis.models.faculty import FacultyCoordinator
        if request and user_has_cis_role(request.user):
            self.fields['courses'].queryset = Course.objects.filter(
                status__iexact='active'
            ).order_by('name')            
        elif request and user_has_faculty_role(request.user):
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

        self.fields['venue'].queryset = Venue.objects.all().order_by('name')

        self.fields['action'].initial = 'edit_event'
        
    class Meta:
        model = Event
        fields = [
            'name',
            'courses',
            'event_type',
            'venue',
            'term',
            'delivery_mode',
            # 'start_time',
            # 'end_time',
            'pd_hour',
            'cost_per_attendee',
            'description',
        ]
        exclude = ['created_by', 'cohort', 'start_time', 'end_time']

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

        record.name = data.get('name')
        record.created_by = request.user

        record.start_time = data.get('start_time')
        record.end_time = data.get('end_time')

        record.save()
        record.courses.clear()

        for course in data.get('courses'):
            record.courses.add(course)

        return record

class EventTypeForm(ModelForm):
    class Meta:
        model = EventType
        fields = '__all__'

class EventVenueForm(ModelForm):
    class Meta:
        model = Venue
        fields = '__all__'


class AttendeeForm(forms.Form):
    name = forms.CharField(
        required=True,
        label='Attendee Name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Jane Doe'})
    )
    email = forms.EmailField(
        required=True,
        label='Attendee Email',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'jane@example.com'})
    )
    position = forms.CharField(
        required=False,
        label='Position',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Counselor, Teacher, etc.'})
    )

from django.forms import ModelChoiceField
from django.utils.timezone import make_aware
class EventChoiceField(ModelChoiceField):
    # make this a radio select field
    def __init__(self, *args, **kwargs):
        kwargs['widget'] = forms.RadioSelect  # <--- This makes it a radio group

        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        # hyper link event.name and open the venue in google maps
        
        if obj.venue:
            return mark_safe(
                f'{obj.venue.name} @ {(datetime.datetime.strftime(timezone.localtime(obj.start_time), "%m/%d/%Y %I:%M %p"))} (<a href="https://www.google.com/maps/dir/?api=1&destination={obj.venue.name},{obj.venue.address} {obj.venue.zip}" target="_blank">Get Directions</a>)'
            )
        return f'{obj.name} @ {obj.venue.name} ({(datetime.datetime.strftime(timezone.localtime(obj.start_time), "%m/%d/%Y %I:%M %p"))})'

class InfoSessionRSVPForm(forms.Form):
    events = forms.ModelChoiceField(
        queryset=None,
        required=True,
        label='Select the session you want to attend',
        widget=forms.RadioSelect(
            attrs={
                'class': 'form-check-input'
            }
        )
    )

    your_name = forms.CharField(
        required=True,
        label='Your Name',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-6',
                'placeholder': 'Dr. John Smith',
            }
        )
    )

    your_email = forms.EmailField(
        label='Your Email',
        help_text='Please enter a valid email',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-5'
            }
        )
    )

    your_role = forms.CharField(
        label='Your Role',
        help_text='Please enter your role',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-5'
            }
        )
    )

    hs_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='High School Information',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )

    highschool_name = forms.CharField(
        required=True,
        label='High School Name',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-6'
            }
        )
    )

    highschool_code = forms.CharField(
        required=False,
        label='High School Code',
        help_text='CEEB Code, if known',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-6'
            }
        )
    )

    highschool_address = forms.CharField(
        required=True,
        label='High School Address Line 1',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-8'
            }
        )
    )

    highschool_city = forms.CharField(
        required=True,
        label='City',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-4'
            }
        )
    )

    highschool_state = forms.CharField(
        required=True,
        label='State/Province',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-4'
            }
        )
    )

    highschool_postal_code = forms.CharField(
        required=True,
        label='Zip / Postal Code',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-3'
            }
        )
    )

    highschool_country = forms.ModelChoiceField(
        label='Country',
        queryset=None
    )

    highschool_phone = forms.CharField(
        required=True,
        label='Phone',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-3'
            }
        )
    )

    highschool_fax = forms.CharField(
        required=False,
        label='Fax',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-3'
            }
        )
    )

    hs_admin_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='Please enter attendee information',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    def __init__(self,info_session, request=None, record=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if request:
            if user_has_cis_role(request.user):
                # del self.fields['captcha']

                self.fields['your_name'].label = 'Submitter Name'
                self.fields['your_email'].label = 'Submitter Email'
        else:
            # del self.fields['captcha']

            self.fields['your_name'].label = 'Submitter Name'
            self.fields['your_email'].label = 'Submitter Email'

        self.fields['action'].initial = 'part_1'
        self.fields['highschool_country'].queryset = Location.objects.all().order_by('name')

        # use event choice field for sessions
        self.fields['events'] = EventChoiceField(
            label='Select the session you want to attend',
            queryset=Event.objects.filter(
            id__in=info_session.sessions.values_list('id', flat=True)
        ))

        if record:
            self.fields['your_name'].initial = record.school_contacts['submitted_by']['name']
            self.fields['your_email'].initial = record.school_contacts['submitted_by']['email']

            self.fields['highschool_name'].initial = record.name
            self.fields['district_name'].initial = record.district

            self.fields['highschool_code'].initial = record.information['address'].get('code')
            self.fields['highschool_address'].initial = record.information['address']['address']
            self.fields['highschool_city'].initial = record.information['address']['city']
            self.fields['highschool_state'].initial = record.information['address']['state']
            self.fields['highschool_postal_code'].initial = record.information['address'].get('postal_code')
            self.fields['highschool_phone'].initial = record.information['address'].get('phone')
            self.fields['highschool_fax'].initial = record.information['address'].get('fax')
            self.fields['highschool_country'].initial = record.information['address']['country_id']

    def save(self, commit=True, app=None):
        data = self.cleaned_data

        rsvp = InfoSessionAttendee.objects.create(
            meta={
                'your_name': self.cleaned_data['your_name'],
                'your_email': self.cleaned_data['your_email'],
                'highschool_name': self.cleaned_data['highschool_name'],
                'highschool_code': self.cleaned_data['highschool_code'],
                'highschool_address': self.cleaned_data['highschool_address'],
                'highschool_city': self.cleaned_data['highschool_city'],
                'highschool_state': self.cleaned_data['highschool_state'],
                'highschool_postal_code': self.cleaned_data['highschool_postal_code'],
                'highschool_phone': self.cleaned_data['highschool_phone'],
                'highschool_fax': self.cleaned_data['highschool_fax'],
                'highschool_country': self.cleaned_data['highschool_country']
            }
        )
                
        # Save attendee formset data
        attendees = []
        if hasattr(self, 'attendee_formset'):
            for form in self.attendee_formset:
                if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                    attendees.append({
                        'name': form.cleaned_data['name'],
                        'email': form.cleaned_data['email'],
                        'position': form.cleaned_data.get('position'),
                    })
        
        rsvp['meta']['attendees'] = attendees
        rsvp.save()

        rsvp.send_confirmation_email()
        return rsvp
    
from .models import COLLEGE_COURSE_OPTIONS

class InfoSessionCourseForm(forms.Form):
    course = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    
    other_college_course = forms.MultipleChoiceField(
        label='What other college level course(s) do you currently offer?',
        choices=COLLEGE_COURSE_OPTIONS,
        required=False,
        widget=forms.CheckboxSelectMultiple
    )

    other_course = forms.CharField(
        required=False,
        label='If other, please specify'
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    def clean(self):
        self.cleaned_data = super().clean()

        course = list(
            map(lambda x:str(x).strip(), self.data.getlist('course')))

        self.cleaned_data['course'] = course
        return self.cleaned_data

    def __init__(self, request, info_session_attendee=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['course'].choices = [
            (course.id, course.id) for course in Course.objects.all()
        ]
            
    def save(self, record, commit=True):
        data = self.cleaned_data

        if not record.meta.get('interested_courses'):
            record.meta['interested_courses'] = []

        record.meta['other_course'] = data.get('other_course')
        record.meta['other_college_course'] = data.get('other_college_course')

        for course_id in data.get('course'):
            course = Course.objects.get(pk=course_id)

            record.meta['interested_courses'].append({
                'course_id': str(course.id),
                'course_name': course.name
            })

        record.save()
        return record
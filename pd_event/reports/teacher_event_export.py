import io, csv, datetime, logging

from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File

from django.http import HttpResponse

from cis.utils import get_field

from cis.backends.storage_backend import PrivateMediaStorage

from django.forms import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models import Event, EventType, EventAttendee

from cis.utils import user_has_cis_role

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.term import Term
from cis.models.highschool import HighSchool
from cis.models.teacher import TeacherHighSchool, TeacherCourseCertificate

logger = logging.getLogger(__name__)

class teacher_event_export(forms.Form):
    
    event_type = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Event Type',
        required=True
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)'
    )

    course = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Course(s)',
        required=True
    )

    course_cert_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Teacher Course Certificate Status'
    )

    started_on = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        required=False,
        label="Event Started On and After")

    started_until = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        required=False,
        label="Event Until")


    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.roles = request.user.get_roles()
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        # if request.user has ce role
        self.fields['event_type'].queryset = EventType.objects.all().order_by('name')
        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        self.fields['course'].queryset = Course.objects.all().order_by('name')

    def run(self, task, data):
        term = data.get('term')

        records = EventAttendee.objects.filter(
            event__event_type__in=data.get('event_type'),
            event__term__id__in=term,
            event__courses__id__in=data.get('course')
        )

        teachers = None
        if data.get('course_cert_status'):
            teachers = TeacherCourseCertificate.objects.filter(
                status__in=data.get('course_cert_status')
            ).values_list('teacher_highschool__teacher__user__psid', flat=True)

        if data.get('started_on')[0]:
            started_on = datetime.datetime.strptime(
                data.get('started_on')[0],
                '%m/%d/%Y'
            )
            records = records.filter(
                event__start_time__gte=started_on
            )

        if data.get('started_until')[0]:
            started_until = datetime.datetime.strptime(
                data.get('started_until')[0],
                '%m/%d/%Y'
            )
            records = records.filter(
                event__start_time__lte=started_until
            )
        
        final_records = [] 
        file_name = "events-attendance-"  + datetime.datetime.now().strftime('%m_%d_%Y') + ".csv"

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        writer = csv.writer(response)


        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        # Write Header
        writer.writerow([
            'First Name',
            'Last Name',
            'EMPLID',
            'Email',
            'Secondary Email',
            'High School',
            'Attendance Type',
            'Attendance Status',           
            'PD Hours',
            'PD Note',
            'Event Type',
            'Event Start Date/Time',
            'Event End Date/Time',
            'Event Course(s)'
        ])

        if records:
            for record in records:                
                row = []
                
                row.append(record.course_certificate.teacher_highschool.teacher.user.first_name)
                row.append(record.course_certificate.teacher_highschool.teacher.user.last_name)
                row.append(record.course_certificate.teacher_highschool.teacher.user.psid)
                row.append(record.course_certificate.teacher_highschool.teacher.user.email)
                row.append(record.course_certificate.teacher_highschool.teacher.user.secondary_email)
                
                row.append(record.course_certificate.teacher_highschool.highschool.name if record.course_certificate.teacher_highschool.highschool else 'Not Available')  # High School Name

                # Filter by teacher course certificate status
                row.append(record.meta.get('attendance_type'))
                row.append(record.meta.get('attendance_status'))
                
                row.append(record.meta.get('pd_hour'))
                
                row.append(record.meta.get('note', ' '))

                row.append(record.event.event_type)
                row.append(record.event.start_time_local.strftime('%m/%d/%Y %I:%M %p'))
                row.append(record.event.end_time_local.strftime('%m/%d/%Y %I:%M %p'))

                row.append(','.join(record.event.course_list))

                writer.writerow(row)

        path = "reports/" + str(datetime.datetime.now().strftime('%Y')) + "/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

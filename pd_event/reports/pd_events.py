import logging, datetime
from operator import or_
from functools import reduce

from django import forms
from django.db.models import Q

from django.urls import reverse_lazy
from django.forms import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.core.files.base import ContentFile, File

from pd_event.models import Event, EventType

from cis.utils import export_to_excel

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort


from django.http import HttpResponse

from cis.utils import get_field

from cis.backends.storage_backend import PrivateMediaStorage

logger = logging.getLogger(__name__)

class pd_events(forms.Form):

    event_type = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Event Type(s)',
        required=True
    )

    cohort = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Subject(s)',
        required=False
    )

    started_on = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        required=False,
        label="Started On and After")

    started_until = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        required=False,
        label="Until")


    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'

        if self.request:
            self.roles = request.user.get_roles()
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
            
        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['cohort'].queryset = Cohort.objects.all().order_by('name')
        self.fields['event_type'].queryset = EventType.objects.all().order_by('name')

    def run(self, task, data):
        cohorts = data.get('cohort')
        
        records = Event.objects.filter(
            event_type__in=data.get('event_type')
        )

        if cohorts and data.get('cohort')[0]:
            cohort_qry = reduce(
                or_, [
                    Q(cohort__contains=str(ch)) for ch in cohorts
                ])
            records = records.filter(
                cohort_qry
            )

        if data.get('started_on')[0]:
            records = records.filter(
                start_time__gte=data.get('started_on')[0]
            )

        if data.get('started_until')[0]:
            records = records.filter(
                start_time__lte=data.get('started_until')[0]
            )
        
        from datetime import datetime
        import csv
        from django.http import HttpResponse

        from django.utils import timezone
        from cis.utils import get_field

        final_records = []

        file_name = "events-export-" + str(datetime.now()) + ".csv"

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        writer = csv.writer(response)

        # Write Header
        writer.writerow([
            'Event Type',
            'Created By',
            'Start Date/Time',
            'End Date/Time',
            'Cohort(s)',
            'Term',
            'PD Hours',
            'Descriptions',
            'Delivery Mode',
            'Description',
            'Guests',
            '# Attended',
            '# Not Attended',
            # '# Attachments'
        ])

        total_pd = 0.0
        if records:
            for record in records:
                row = []
                row.append(record.event_type)
                row.append(record.created_by)

                row.append(timezone.localtime(record.start_time).strftime('%m/%d/%Y %I:%M %p'))
                row.append(timezone.localtime(record.end_time).strftime('%m/%d/%Y %I:%M %p'))
                row.append(record.cohorts)
                row.append(record.term)
                row.append(record.pd_hour)
                row.append(record.description)
                row.append(record.delivery_mode)
                row.append(record.description)
                
                row.append(record.num_guests)
                row.append(record.num_attendees)
                row.append(record.num_not_attended)

                # row.append(record.num_attachments)

                # try:
                #     total_pd += float(record.pd_hour)
                # except:
                #     pass

                writer.writerow(row)

            # writer.writerow([
            #     '', '', '', '', '', total_pd
            # ])

        path = "reports/" + str(datetime.now().strftime('%Y')) + "/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(response.getvalue()))
        path = media_storage.url(path)

        return path

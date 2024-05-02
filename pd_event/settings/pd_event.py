import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term, AcademicYear
from cis.models.settings import Setting
from cis.validators import validate_html_short_code

class SettingForm(forms.Form):

    # send_reminder_on = forms.CharField(
    #     max_length=None,
    #     widget=forms.HiddenInput,
    #     help_text='Comma separated days - not used',
    #     required=False,
    #     label="Send Reminder these # of days prior to event")

    event_reminder_subject = forms.CharField(
        max_length=None,
        widget=forms.HiddenInput,
        required=False,
        label="Event Reminder Email Subject")

    event_reminder_template = forms.CharField(
        max_length=None,
        # widget=forms.Textarea,
        widget=forms.HiddenInput,
        required=False,
        validators=[validate_html_short_code],
        help_text='{{attendee_first_name}}, {{attendee_last_name}}, {{cohort}}, {{term}}, {{pd_hour}}, {{start_date_time}}, {{end_date_time}}, {{event_type}}, {{description}}',
        label="Event Reminder Email Template")
    
    event_signin_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Formatted HTML with support for {{cohort}}, {{term}}, {{start_date_time}}, {{end_date_time}}, {{event_type}}, {{delivery_mode}}, {{guest_list}}. <a href="#" class="float-right" onClick="do_bulk_action(\'pd_event\', \'event_signin_template\')" >See Preview</a>',
        label="Attendance Sheet Template")

    pd_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Formatted HTML with support for {{attendee_first_name}}, {{attendee_last_name}}, {{cohort}}, {{term}}, {{earned_pd_hour}}, {{start_date_time}}, {{end_date_time}}, {{event_type}}, {{pd_note}}, {{delivery_mode}}. <a href="#" class="float-right" onClick="do_bulk_action(\'pd_event\', \'pd_template\')" >See Preview</a>',
        label="PD Letter Template")

    pd_email_subject = forms.CharField(
        label='PD Letter Email Subject'
    )

    pd_email_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='PD letter email {{attendee_first_name}}, {{attendee_last_name}}, {{cohort}}, {{term}}, {{earned_pd_hour}}, {{start_date_time}}, {{end_date_time}}, {{event_type}}, {{pd_note}}, {{delivery_mode}}, {{pd_letter_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'pd_event\', \'pd_email_template\')" >See Preview</a>',
        label="PD Letter Email Template")


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'event_reminder_template': self.cleaned_data.get('event_reminder_template'),
            'event_reminder_subject': self.cleaned_data.get('event_reminder_subject'),
            # 'send_reminder_on': self.cleaned_data.get('send_reminder_on'),
            'pd_template': self.cleaned_data.get('pd_template'),
            'event_signin_template': self.cleaned_data.get('event_signin_template'),
            'pd_email_subject': self.cleaned_data.get('pd_email_subject'),
            'pd_email_template': self.cleaned_data.get('pd_email_template'),
        }

class pd_event(SettingForm):
    key = "pd_event"

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def install(self):
        defaults = {
            'event_reminder_template': "Change this in Settings -> Misc -> PD Event",
            'send_reminder_on': "7",
            'pd_template': "Change this in Settings -> Misc -> PD Event",
            'event_signin_template': "Change this in Settings -> Misc -> PD Event",
            'pd_email_subject': "Change this in Settings -> Misc -> PD Event",
            'pd_email_template': "Change this in Settings -> Misc -> PD Event",
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        if field_name in ['pd_template']:
            base_template = 'pd_event/base.html'
            pd_template = self.from_db().get('pd_template', '')
            
            pd_template = Template(pd_template)
            pd_html = pd_template.render(Context({
                'attendee_first_name': 'First Name',
                'attendee_last_name': 'Last Name',
                'cohort': 'Cohorts',
                'term': 'Term',
                'earned_pd_hour': '10',
                'start_date_time': '11/18/2018 12:02',
                'end_date_time': '12/01/1977 5:43',  
                'event_type': 'Event Type',
                'pd_note': 'PD Note',
                'delivery_mode': 'Del Mode',
                'description': "Description"
            }))

            return render(
                request,
                base_template,
                {'main_content': pd_html}
            )
        elif field_name in ['event_signin_template']:
            base_template = 'pd_event/base.html'
            pd_template = self.from_db().get('event_signin_template', '')
            
            attendee_list = render_to_string(
                'pd_event/event-attendee-list.html', {
                    'attendees': [
                        'Name 1', 'Name 2'
                    ]
                })

            pd_template = Template(pd_template)
            pd_html = pd_template.render(Context({
                'cohort': "Cohort Name",
                'term': "Term",
                'earned_pd_hour': "100",
                'start_date_time': "12/01/1977 05:43",
                'end_date_time': "11/18/2018 12:22",
                'event_type': "Event Type",
                'delivery_mode': "Delivery Mode",
                "guest_list": attendee_list,
                'pd_letter_url': "https://pd_letter_url",
            }))

            return render(
                request,
                base_template,
                {'main_content': pd_html}
            )
        elif field_name in ['pd_email_template']:
            email_settings = self.from_db()

            email = email_settings.get('pd_email_template')
            subject = email_settings.get('password_reset_subject')

            email_template = Template(email)
            context = Context({
                'attendee_first_name': request.user.first_name,
                'attendee_last_name': request.user.last_name,
                'cohort': "Cohort Name",
                'term': "Term",
                'earned_pd_hour': "100",
                'start_date_time': "12/01/1977 05:43",
                'end_date_time': "11/18/2018 12:22",
                'event_type': "Event Type",
                'delivery_mode': "Delivery Mode",
                'pd_letter_url': "https://pd_letter_url",
            })

            text_body = email_template.render(context)
            
            return render(
                request,
                'cis/email.html',
                {
                    'message': text_body
                }
            )

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})

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


def _install_defaults(key, defaults):
    """Create the setting, or add only the keys it lacks (package-cis #19/#51).

    Setting.install_defaults when the installed cis ships it (v0.0.39+);
    otherwise the same merge inline, because this package also runs on
    tenants pinned to an older cis. Never overwrites a customised value.
    """
    helper = getattr(Setting, 'install_defaults', None)
    if helper is not None:
        return helper(key, defaults)
    setting, created = Setting.objects.get_or_create(
        key=key, defaults={'value': dict(defaults)})
    if not created:
        stored = setting.value if isinstance(setting.value, dict) else {}
        missing = {k: v for k, v in defaults.items() if k not in stored}
        if missing:
            stored.update(missing)
            setting.value = stored
            setting.save()
    return setting
from cis.validators import validate_html_short_code

class SettingForm(forms.Form):

    # send_reminder_on = forms.CharField(
    #     max_length=None,
    #     widget=forms.HiddenInput,
    #     help_text='Comma separated days - not used',
    #     required=False,
    #     label="Send Reminder these # of days prior to event")

    # do you want to track pd event cost
    track_pd_event_cost = forms.BooleanField(
        required=False,
        label="Track PD Event Cost",
        help_text="If checked, you will be able to track the cost of PD events.",
        initial=False
    )
    
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


    # Automatic follow-ups (#16). Off by default.
    remind_unmarked_attendance = forms.BooleanField(
        required=False,
        label='Remind CE when an event ends with attendance not marked',
        help_text='One email per run listing ended events that still have guests not marked. '
                  'Each event is reminded about once.',
    )
    unmarked_attendance_days = forms.IntegerField(
        required=False,
        min_value=0,
        initial=1,
        label='Days after the event ends',
    )
    unmarked_attendance_recipients = forms.CharField(
        required=False,
        label='Send attendance reminders to',
        help_text='Comma-separated emails. Blank sends each reminder to whoever created the event.',
    )
    email_missed_required = forms.BooleanField(
        required=False,
        label='Email guests who missed a required event',
        help_text='Sent once to each guest marked Not Attended for a required event that '
                  'ended in the last 30 days.',
    )
    missed_required_subject = forms.CharField(
        required=False,
        label='Missed required event email subject',
    )
    missed_required_template = forms.CharField(
        required=False,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='{{attendee_first_name}}, {{attendee_last_name}}, {{course}}, {{term}}, '
                  '{{start_date_time}}, {{end_date_time}}, {{event_type}}, {{delivery_mode}}, '
                  '{{description}}',
        label='Missed required event email',
    )
    followup_cron = forms.CharField(
        required=False,
        initial='0 7 * * *',
        label='Follow-ups schedule (cron)',
        help_text='When the pd_event_followups command runs. Default: 7am daily.',
    )
    followup_debug_email_list = forms.CharField(
        required=False,
        label='Follow-up debug email list',
        help_text='Comma-separated. On a DEBUG site, follow-ups go only here (or nowhere if blank).',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get('email_missed_required') and not data.get('missed_required_subject'):
            self.add_error('missed_required_subject', 'Needed to email guests who missed a required event.')
        if data.get('email_missed_required') and not data.get('missed_required_template'):
            self.add_error('missed_required_template', 'Needed to email guests who missed a required event.')
        cron = (data.get('followup_cron') or '').strip()
        if cron:
            try:
                from cis.validators import validate_cron
                validate_cron(cron)
            except ImportError:
                pass
            except ValidationError as e:
                self.add_error('followup_cron', e)
        return data

    def _schedule_followups(self):
        """Create or update the cron row when a follow-up is on. Turned off,
        the row stays (deleting it would drop its run history); the command
        does nothing then."""
        if not (self.cleaned_data.get('remind_unmarked_attendance')
                or self.cleaned_data.get('email_missed_required')):
            return
        from cis.models.crontab import CronTab
        cron, _ = CronTab.objects.get_or_create(command='pd_event_followups')
        cron.cron = (self.cleaned_data.get('followup_cron') or '0 7 * * *').strip()
        cron.save()

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'event_reminder_template': self.cleaned_data.get('event_reminder_template'),
            'event_reminder_subject': self.cleaned_data.get('event_reminder_subject'),
            'track_pd_event_cost': self.cleaned_data.get('track_pd_event_cost'),
            # 'send_reminder_on': self.cleaned_data.get('send_reminder_on'),
            'pd_template': self.cleaned_data.get('pd_template'),
            'event_signin_template': self.cleaned_data.get('event_signin_template'),
            'pd_email_subject': self.cleaned_data.get('pd_email_subject'),
            'pd_email_template': self.cleaned_data.get('pd_email_template'),
            **self._followups(),
        }

    def _followups(self):
        self._schedule_followups()
        days = self.cleaned_data.get('unmarked_attendance_days')
        return {
            'remind_unmarked_attendance': bool(self.cleaned_data.get('remind_unmarked_attendance')),
            'unmarked_attendance_days': 1 if days is None else days,
            'unmarked_attendance_recipients': self.cleaned_data.get('unmarked_attendance_recipients', ''),
            'email_missed_required': bool(self.cleaned_data.get('email_missed_required')),
            'missed_required_subject': self.cleaned_data.get('missed_required_subject', ''),
            'missed_required_template': self.cleaned_data.get('missed_required_template', ''),
            'followup_cron': (self.cleaned_data.get('followup_cron') or '0 7 * * *').strip(),
            'followup_debug_email_list': self.cleaned_data.get('followup_debug_email_list', ''),
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
            # Follow-ups (#16): off until CE turns them on.
            'remind_unmarked_attendance': False,
            'unmarked_attendance_days': 1,
            'unmarked_attendance_recipients': '',
            'email_missed_required': False,
            'missed_required_subject': 'You missed a required PD event: {{event_type}}',
            'missed_required_template': (
                '<p>Hi {{attendee_first_name}},</p><p>Our records show you did not attend '
                '{{event_type}} on {{start_date_time}} ({{term}}), which was required. '
                'Please contact us about make-up options.</p>'),
            'followup_cron': '0 7 * * *',
            'followup_debug_email_list': '',
        }

        _install_defaults(self.key, defaults)

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

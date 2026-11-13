"""Automatic follow-ups after PD events (#16). Both are off by default.

- **Unmarked attendance:** once an event ended ``unmarked_attendance_days``
  ago with guests still not marked, email CE (``unmarked_attendance_recipients``,
  else the event's creator) one digest listing those events. Each event is
  reminded about once (``Event.meta['unmarked_reminder_sent_on']``).
- **Missed required:** email each guest marked Not Attended for a required
  event, using the ``missed_required_subject`` / ``missed_required_template``
  setting. Once per guest row (``meta['missed_required_emailed_on']``).

Only events that ended in the last ``LOOKBACK_DAYS`` are considered, so
turning a follow-up on does not email about years of past events.

With ``settings.DEBUG`` on, mail goes to ``followup_debug_email_list`` only,
or nowhere when it is empty.

Run by the ``pd_event_followups`` command (cron row created when the
setting is saved with either follow-up on).
"""
import datetime
from collections import OrderedDict

from django.conf import settings
from django.template import Context, Template
from django.utils.html import escape
from django.template.loader import get_template
from django.utils import timezone

from mailer import send_html_mail

from .summary import KEY_NOT_MARKED, event_attendees, is_required_missed, status_key

LOOKBACK_DAYS = 30


def _settings():
    try:
        from cis.settings.pd_event import pd_event as pd_settings
        return pd_settings.from_db() or {}
    except Exception:
        return {}


def _addresses(value):
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else (
        str(value).replace('\n', ',').replace(';', ',').split(','))
    return [a.strip() for a in items if a and str(a).strip()]


def _recipients(config, to):
    """Who actually gets it: the debug list under DEBUG, else `to`."""
    if getattr(settings, 'DEBUG', False):
        return _addresses(config.get('followup_debug_email_list'))
    return list(dict.fromkeys(_addresses(to)))


def _send(config, subject, body, to, dry_run):
    recipients = _recipients(config, to)
    if recipients and not dry_run:
        html = get_template('cis/email.html').render({'message': body})
        send_html_mail(subject, body, html, settings.DEFAULT_FROM_EMAIL, recipients)
    return recipients


def _today():
    return timezone.localdate().strftime('%m/%d/%Y')


def _ended_events(days):
    from ..models import Event
    now = timezone.now()
    return Event.objects.filter(
        end_time__lte=now - datetime.timedelta(days=days),
        end_time__gte=now - datetime.timedelta(days=LOOKBACK_DAYS),
    ).select_related('event_type', 'term', 'created_by').order_by('end_time')


def remind_unmarked(config, dry_run=False):
    days = config.get('unmarked_attendance_days')
    try:
        days = min(LOOKBACK_DAYS - 1, max(0, int(1 if days in (None, '') else days)))
    except (TypeError, ValueError):
        days = 1

    # recipients (tuple) -> events to list for them
    digests = OrderedDict()
    for event in _ended_events(days):
        if (event.meta or {}).get('unmarked_reminder_sent_on'):
            continue
        unmarked = sum(1 for a in event_attendees(event) if status_key(a) == KEY_NOT_MARKED)
        if not unmarked:
            continue
        to = _addresses(config.get('unmarked_attendance_recipients')) or (
            [event.created_by.email] if event.created_by_id and event.created_by.email else [])
        digests.setdefault(tuple(to), []).append((event, unmarked))

    from cis.utils import getDomain
    log = []
    for to, events in digests.items():
        lines = ''.join(
            f'<li><a href="{getDomain()}{event.ce_url}">{escape(event.name or event.event_type)}</a>'
            f' ({escape(event.term.label)}, {timezone.localtime(event.end_time).strftime("%m/%d/%Y")}):'
            f' {unmarked} guest(s) not marked</li>'
            for event, unmarked in events)
        body = (f'<p>These PD events have ended but attendance is not fully marked:</p>'
                f'<ul>{lines}</ul><p>Open each event, then Manage Attendance.</p>')
        sent_to = _send(config, 'PD events need attendance marked', body, list(to), dry_run)
        for event, unmarked in events:
            log.append({'event': str(event.id), 'name': event.name or str(event.event_type),
                        'unmarked': unmarked, 'to': sent_to})
            if not dry_run and sent_to:
                event.meta = {**(event.meta or {}), 'unmarked_reminder_sent_on': _today()}
                event.save(update_fields=['meta'])
    return log


def email_missed_required(config, dry_run=False):
    subject_template = Template(config.get('missed_required_subject') or '')
    body_template = Template(config.get('missed_required_template') or '')
    log = []
    for event in _ended_events(0):
        for attendee in event_attendees(event):
            if not is_required_missed(attendee):
                continue
            if (attendee.meta or {}).get('missed_required_emailed_on'):
                continue
            person = attendee.recipient()
            if not person or not person['emails']:
                continue
            context = Context(attendee.letter_context(person))
            sent_to = _send(config, subject_template.render(context).strip(),
                            body_template.render(context), person['emails'], dry_run)
            log.append({'attendee': str(attendee.id), 'event': str(event.id),
                        'name': f"{person['first_name']} {person['last_name']}",
                        'to': sent_to})
            if not dry_run and sent_to:
                attendee.meta['missed_required_emailed_on'] = _today()
                attendee.save()
    return log


def run(dry_run=False):
    """Both follow-ups as configured. Returns (summary, detailed_log)."""
    config = _settings()
    log = {'unmarked_attendance': [], 'missed_required': []}
    if config.get('remind_unmarked_attendance'):
        log['unmarked_attendance'] = remind_unmarked(config, dry_run=dry_run)
    if config.get('email_missed_required') and config.get('missed_required_subject'):
        log['missed_required'] = email_missed_required(config, dry_run=dry_run)
    prefix = 'Would send' if dry_run else 'Sent'
    summary = (f"{prefix}: {len(log['unmarked_attendance'])} event(s) in attendance reminders, "
               f"{len(log['missed_required'])} missed-required email(s).")
    return summary, log

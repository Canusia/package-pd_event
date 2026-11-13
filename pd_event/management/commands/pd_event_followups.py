"""PD event follow-ups (#16): unmarked-attendance reminders to CE and
missed-required emails to guests. Both are off until turned on in the PD
Event setting; see services/followups.py."""
import json

from django.core.management.base import BaseCommand

from ...admin_runner import register_command
from ...services.followups import run


@register_command(
    group='pd_event',
    permission='pd_event.change_event',
    # -t/--time is cron bookkeeping, not something to type in the admin.
    exclude_params=['time'],
)
class Command(BaseCommand):
    help = ('Email CE about ended PD events with attendance not marked, and guests who '
            'missed a required event (each as configured). Use --dry-run to preview.')

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be sent; send and save nothing')

    def handle(self, *args, **kwargs):
        time = kwargs.get('time')
        dry_run = kwargs.get('dry_run', False)

        # cis's cron receivers parse the scheduled time and crash on None,
        # so only report to the cron log when cron started the run.
        if time:
            from cis.signals.crontab import cron_task_started
            cron_task_started.send(sender=self.__class__, task=self.__class__,
                                   scheduled_time=time)

        summary, log = run(dry_run=dry_run)
        self.stdout.write(summary)
        if dry_run:
            for row in log['unmarked_attendance']:
                self.stdout.write(f"  attendance reminder: {row['name']} "
                                  f"({row['unmarked']} not marked) -> {', '.join(row['to']) or 'nobody'}")
            for row in log['missed_required']:
                self.stdout.write(f"  missed required: {row['name']} -> {', '.join(row['to']) or 'nobody'}")

        if time:
            from cis.signals.crontab import cron_task_done
            cron_task_done.send(sender=self.__class__, task=self.__class__,
                                scheduled_time=time, summary=summary,
                                detailed_log=json.dumps(log))

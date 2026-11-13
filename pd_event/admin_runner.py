"""django-admin-runner hook (#16).

Lets pd_event commands be run from the Django admin when the host has
``django_admin_runner`` installed. Optional: without it the decorator does
nothing and the commands still run from ``manage.py`` and cron.
"""
try:
    from django_admin_runner import register_command  # noqa: F401
except ImportError:  # runner not installed: the decorator does nothing
    def register_command(*args, **kwargs):
        return lambda cls: cls

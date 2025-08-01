from django.urls import path, include

from ..views.info_session import (
    start_rsvp
)

app_name = 'events'

from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path('info_session/start_rsvp/', start_rsvp, name='start_rsvp'),
]

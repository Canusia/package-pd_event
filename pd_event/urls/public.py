from django.urls import path, include

from ..views.info_session import (
    start_rsvp,
    submit_info_session_courses
)

app_name = 'info_session'

from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path('info_session/start_rsvp/<uuid:info_session_id>/', start_rsvp, name='start_rsvp'),
    path('info_session/interested_courses/<uuid:rsvp_id>/', submit_info_session_courses, name='submit_info_session_courses'),
]

from django.urls import path, include

from pd_event.views.event_type import (
    index as event_types,
    detail as event_type,
    add_new as add_event_type,
    EventTypeViewSet
)

from pd_event.views.event import (
    index as events,
    detail as event,
    add_new as add_event,
    search_guest_list,
    add_attendee,
    remove_attendee,
    toggle_attendee,
    remove_upload,
    mark_attendance,
    export_attendee_list,
    update_count,
    attendees,
    get_courses,
    EventViewSet,
    pd_letter,
    email_pd_letter,
    event_signin_sheet,
    send_reminder
)
from rest_framework import routers

app_name = 'pd_event_faculty'

router = routers.DefaultRouter()
router_viewsets = {
    'event_types': EventTypeViewSet,
    'events': EventViewSet
}

for router_key in router_viewsets.keys():
    router.register(
        router_key,
        router_viewsets[router_key],
        basename=app_name
    )

urlpatterns = [
    path('api/', include(router.urls)),

    path('get_courses/', get_courses, name='get_courses'),
    
    path('event_types/', event_types, name='event_types'),
    path('event_type/<uuid:record_id>/', event_type, name='event_type'),
    path('event_type/add_new/', add_event_type, name='event_type_add_new'),

    path('', events, name='events'),
    path('search_guest_list/', search_guest_list, name='search_guest_list'),
    path('event/add_new/', add_event, name='event_add_new'),
    path('event/<uuid:record_id>/', event, name='event'),
    path('event/<uuid:record_id>/export_attendee/', export_attendee_list, name='export_attendee_list'),
    path('event/<uuid:record_id>/send_reminder/', send_reminder, name='send_reminder_email'),
    path('event/<uuid:record_id>/export_signin_sheet/', event_signin_sheet, name='export_signin_sheet'),
    path('event/remove_upload/<uuid:record_id>', remove_upload, name='remove_upload'),
    path('event/pd_letter/<uuid:attendance_id>', pd_letter, name='pd_letter'),
    path('event/email_pd_letter/<uuid:record_id>', email_pd_letter, name='email_pd_letter'),
    path('event/<uuid:record_id>/attendee/add_new/', add_attendee, name='add_attendee'),
    path('event/<uuid:record_id>/attendee/remove/', remove_attendee, name='remove_attendee'),
    path('event/<uuid:record_id>/attendee/toggle/', toggle_attendee, name='toggle_attendee'),
    path('event/<uuid:record_id>/attendees/', attendees, name='attendees'),
    path('event/<uuid:record_id>/mark_attendance/', mark_attendance, name='mark_attendance'),
    path('event/<uuid:record_id>/update_count/', update_count, name='update_count'),
]

from django.urls import path

from ..views.highschool_admin import events

app_name = 'pd_event_highschool_admin'

urlpatterns = [
    path('', events, name='events'),
]

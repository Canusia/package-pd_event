from django.urls import path, include
from rest_framework import routers

from ..views.instructor import index, InstructorEventAttendeeViewSet

app_name = 'pd_event_instructor'

router = routers.DefaultRouter()
router.register('attendees', InstructorEventAttendeeViewSet, basename='attendees')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', index, name='index'),
]

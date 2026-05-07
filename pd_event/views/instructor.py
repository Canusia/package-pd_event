from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from rest_framework import viewsets

from cis.models.teacher import Teacher
from cis.utils import INSTRUCTOR_user_only

from ..models import EventAttendee
from ..serializers import InstructorEventAttendeeSerializer


@login_required
def index(request):
    api_url = reverse('pd_event_instructor:attendees-list') + '?format=datatables'
    return render(request, 'pd_event/instructor-event-list.html', {
        'page_name': 'My PD Events',
        'api_url': api_url,
    })


class InstructorEventAttendeeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InstructorEventAttendeeSerializer
    permission_classes = [INSTRUCTOR_user_only]

    def get_queryset(self):
        try:
            teacher = self.request.user.teacher
        except Teacher.DoesNotExist:
            return EventAttendee.objects.none()
        return (
            EventAttendee.objects
            .filter(
                type='instructor',
                course_certificate__teacher_highschool__teacher=teacher,
            )
            .select_related(
                'event',
                'event__event_type',
                'event__term',
                'event__term__academic_year',
                'course_certificate__course',
            )
            .order_by('-event__term__academic_year__name', '-event__term__label', '-event__start_time')
        )

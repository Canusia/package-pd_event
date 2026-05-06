from django.contrib.auth import get_user_model

from rest_framework import serializers
from django.urls import reverse
from cis.models.course import Cohort

from cis.serializers.term import TermSerializer
from cis.serializers.highschool_admin import CustomUserSerializer
from cis.serializers.course import CourseSerializer
from .models import (
    Event, EventType, EventFile,
    EventAttendee
)

class EventTypeSerializer(serializers.ModelSerializer):
    ce_url = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = EventType
        fields = '__all__'

class EventSerializer(serializers.ModelSerializer):
    event_type = EventTypeSerializer()
    term = TermSerializer()

    start_time = serializers.DateTimeField(
        format='%m/%d/%Y %H:%M'
    )

    end_time = serializers.DateTimeField(
        format='%m/%d/%Y %H:%M'
    )

    course_list = serializers.ListField()
    courses = CourseSerializer(
        many=True,
        read_only=True
    )
    class Meta:
        model = Event
        fields = '__all__'



class InstructorEventAttendeeSerializer(serializers.ModelSerializer):
    """Read-only serializer for the instructor portal event list.

    Exposes pd_letter_url only when attendance_status == 'attended'.

    Callers must supply a queryset prefetched with::

        .select_related(
            'event',
            'event__event_type',
            'event__term',
            'course_certificate__course',
        )
    """
    event = serializers.SerializerMethodField()
    course = serializers.SerializerMethodField()
    attendance_status = serializers.SerializerMethodField()
    pd_letter_url = serializers.SerializerMethodField()

    class Meta:
        model = EventAttendee
        fields = ('id', 'event', 'course', 'attendance_status', 'pd_letter_url')

    def get_event(self, obj):
        return {
            'id': str(obj.event.id),
            'name': obj.event.name,
            'event_type': str(obj.event.event_type) if obj.event.event_type_id else '',
            'start_time': obj.event.start_time_local.strftime('%m/%d/%Y %H:%M') if obj.event.start_time else '',
            'end_time': obj.event.end_time_local.strftime('%m/%d/%Y %H:%M') if obj.event.end_time else '',
            'delivery_mode': obj.event.delivery_mode,
            'term': str(obj.event.term) if obj.event.term_id else '',
        }

    def get_course(self, obj):
        if obj.course_certificate_id and obj.course_certificate.course_id:
            return obj.course_certificate.course.name
        return ''

    def get_attendance_status(self, obj):
        return (obj.meta or {}).get('attendance_status') or ''

    def get_pd_letter_url(self, obj):
        if (obj.meta or {}).get('attendance_status') == 'attended':
            return reverse('pd_event:pd_letter', kwargs={'attendance_id': obj.id})
        return None


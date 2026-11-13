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

    # 12-hour, as the event form shows it (#9).
    start_time = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p'
    )

    end_time = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p'
    )

    course_list = serializers.ListField()
    courses = CourseSerializer(
        many=True,
        read_only=True
    )

    # Guest counts and status (#9), from EventViewSet's annotations.
    num_invited = serializers.SerializerMethodField()
    num_attended = serializers.SerializerMethodField()
    num_not_attended = serializers.SerializerMethodField()
    num_not_marked = serializers.SerializerMethodField()
    attendance_rate = serializers.SerializerMethodField()
    attendance_status_label = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = '__all__'
        # The datatables format drops fields that are not table columns; the
        # list's Start / End cell also shows end_time.
        datatables_always_serialize = ('id', 'end_time')

    @staticmethod
    def _counts(obj):
        # att_* names: Event already has num_* properties.
        invited = getattr(obj, 'att_invited', None)
        if invited is None:  # not annotated: count here
            invited = obj.num_guests
            attended, not_attended = obj.num_attendees, obj.num_not_attended
        else:
            attended, not_attended = obj.att_attended, obj.att_not_attended
        return invited, attended, not_attended, invited - attended - not_attended

    def get_num_invited(self, obj):
        return self._counts(obj)[0]

    def get_num_attended(self, obj):
        return self._counts(obj)[1]

    def get_num_not_attended(self, obj):
        return self._counts(obj)[2]

    def get_num_not_marked(self, obj):
        return self._counts(obj)[3]

    def get_attendance_rate(self, obj):
        from .services.summary import rate
        invited, attended, _, _ = self._counts(obj)
        return rate(attended, invited)

    def get_attendance_status_label(self, obj):
        """Upcoming / Needs attendance / Complete / No guests."""
        from django.utils import timezone
        if obj.start_time and obj.start_time > timezone.now():
            return 'Upcoming'
        invited, _, _, not_marked = self._counts(obj)
        if not invited:
            return 'No guests'
        return 'Needs attendance' if not_marked else 'Complete'



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


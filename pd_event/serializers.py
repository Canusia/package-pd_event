from django.contrib.auth import get_user_model

from rest_framework import serializers
from cis.models.course import Cohort

from cis.serializers.term import TermSerializer
from cis.serializers.highschool_admin import CustomUserSerializer
from cis.serializers.course import CourseSerializer
from .models import (
    Event, EventType, EventFile,
    EventAttendee, Venue,
    InfoSession, InfoSessionNote, InfoSessionAttendee
)

class InfoSessionAttendeeSerializer(serializers.ModelSerializer):
    created_on = serializers.DateTimeField(
        format='%m/%d/%Y %H:%M',
        read_only=True
    )
    interested_courses = serializers.ListField(allow_empty=True)
    other_college_courses = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        read_only=True
    )
    highschool_name = serializers.CharField(read_only=True)
    highschool_state = serializers.CharField(read_only=True)
    submitted_by = serializers.CharField(read_only=True)
    submitted_by_email = serializers.CharField(read_only=True)
    selected_session = serializers.CharField(read_only=True)
    number_of_attendees = serializers.IntegerField(read_only=True)

    class Meta:
        model = InfoSessionAttendee
        fields = '__all__'

class EventTypeSerializer(serializers.ModelSerializer):
    ce_url = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = EventType
        fields = '__all__'

# add venue serializer
class VenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = '__all__'
        
class EventSerializer(serializers.ModelSerializer):
    event_type = EventTypeSerializer()
    term = TermSerializer()
    venue = VenueSerializer()

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


class InfoSessionSerializer(serializers.ModelSerializer):
    term = TermSerializer()
    notes = serializers.SerializerMethodField()
    attendees = serializers.SerializerMethodField()

    sessions = EventSerializer(
        many=True,
        read_only=True
    )

    rsvp_url = serializers.CharField(
        read_only=True
    )
    created_by = CustomUserSerializer(
        read_only=True
    )
    
    class Meta:
        model = InfoSession
        fields = '__all__'
        datatables_always_serialize = (
            'id', 'rsvp_url'
        )
    def get_notes(self, obj):
        return InfoSessionNote.objects.filter(info_session=obj).values()

    def get_attendees(self, obj):
        return InfoSessionAttendee.objects.filter(info_session=obj).values()
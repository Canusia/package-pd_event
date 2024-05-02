from django.contrib.auth import get_user_model

from rest_framework import serializers
from cis.models.course import Cohort

from cis.serializers.term import TermSerializer
from cis.serializers.highschool_admin import CustomUserSerializer

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

    cohorts = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = '__all__'

    def get_cohorts(self, obj):
        if obj.cohort:
            cohorts = Cohort.objects.filter(
                id__in=obj.cohort
            ).order_by('name')

            return '<br>'.join(cohort.name for cohort in cohorts)
        return 'N/A'
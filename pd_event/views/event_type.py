
from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import EventType
from ..serializers import EventTypeSerializer
from ..forms import EventTypeForm

from cis.menu import cis_menu, draw_menu

from cis.utils import CIS_user_only, FACULTY_user_only

class EventTypeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EventTypeSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only]

    def get_queryset(self):
        records = EventType.objects.all()
        return records

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'pd_event/event_type.html'
    record = get_object_or_404(EventType, pk=record_id)

    if request.method == 'POST':
        form = EventTypeForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('pd_event:event_type', record_id=record_id)
    else:
        form = EventTypeForm(instance=record)

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Event Type",
            'labels': {
                'all_items': 'All Types'
            },
            'urls': {
                'add_new': 'pd_event:event_type_add_new',
                'all_items': 'pd_event:event_types'
            },
            'menu': draw_menu(cis_menu, 'events', 'pd_event:event_type'),
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'pd_event/event_type-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = EventTypeForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            if ajax == '1':
                data = {
                    'status':'success',
                    'message':'Successfully added new record',
                    'new_record_id':record.id,
                    'new_record_name':record.name
                }
                return JsonResponse(data)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success') 
            return redirect('pd_event:event_type', record_id=record.id)
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = EventTypeForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New Type",
            'labels': {
                'all_items': 'All Types'
            },
            'urls': {
                'add_new': 'pd_event:event_type_add_new',
                'all_items': 'pd_event:event_types'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'pd_event:event_type')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'events', 'pd_event:event_type')
    template = 'pd_event/event_type-list.html'

    return render(
        request,
        template, {
            'page_title': 'Event Types',
            'urls': {
                'add_new': 'pd_event:event_type_add_new',
                'details_prefix': '/ce/events/event_type/'
            },
            'menu': menu,
            'api_url': '/ce/events/api/event_types?format=datatables'
        }
    )

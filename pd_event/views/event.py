import datetime, os, logging, csv

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils import timezone

from django.template import Template, Context
from django.template.loader import get_template

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.models.faculty import FacultyCoordinator, FacultyCourseCoordinator
from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.course import Cohort, CohortParticipant, CohortAffiliation, Course, CourseAdministrator
from cis.models.note import EventNote
from cis.models.teacher import (
    TeacherCourseCertificate,
    Teacher
)

from ..models import EventType, Event, EventFile, EventAttendee
from ..serializers import EventSerializer
from ..forms import EventForm, EventFileForm, EventAttendeeFilterForm, EventEmailForm

from cis.menu import cis_menu, draw_menu, FACULTY_MENU

from cis.utils import CIS_user_only, user_has_faculty_role, FACULTY_user_only

class EventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EventSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only]

    def get_queryset(self):
        records = Event.objects.all()

        if user_has_faculty_role(self.request.user):
            try:
                faculty = FacultyCoordinator.objects.get(
                    user=self.request.user
                )

                records = records.filter(
                    cohort__contains=str(faculty.cohort.id)
                )
            except:
                pass
        
        if self.request.GET.get('term'):
            records = records.filter(
                term__code=self.request.GET.get('term')
            )
        if self.request.GET.get('event_type'):
            records = records.filter(
                event_type__id=self.request.GET.get('event_type')
            )

        if self.request.GET.get('cohort'):
            records = records.filter(
                cohort__contains=self.request.GET.get('cohort')
            )
        
        if self.request.GET.get('start_time'):
            records = records.filter(
                start_time__gte=datetime.datetime.strptime(
                    self.request.GET.get('start_time'), '%m/%d/%Y'
                )
            )

        if self.request.GET.get('end_time'):
            records = records.filter(
                start_time=datetime.datetime.strptime(
                    self.request.GET.get('end_time'), '%m/%d/%Y %H:%M'
                )
            )
        return records

def remove_upload(request, record_id):
    try:
        upload = EventFile.objects.get(
            pk=record_id
        )
        event = upload.event
        upload.delete()

        messages.add_message(
            request,
            messages.SUCCESS,
            f'Successfully removed file.',
            'list-group-item-success')
        return redirect(
            'pd_event:event',
            record_id=event.id
        )
    except:
        messages.add_message(
            request,
            messages.SUCCESS,
            f'Unable to remove file.',
            'list-group-item-error')
        return redirect(
            'pd_event:event',
            record_id=event.id
        )

def email_pd_letter(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendee_ids = request.POST.getlist('attendee', None)
    
    attendees = EventAttendee.objects.filter(
        event=event,
        id__in=attendee_ids
    )

    if not attendees:
        return JsonResponse({
            'status': 'warning',
            'message': 'Please select the attendees and try again'
        })

    sent_count = 0
    for a in attendees:
        if a.meta['attendance_status'] == 'attended':    
            if a.send_pd_letter():
                a.meta['pd_letter_sent_on'] = datetime.datetime.now().strftime('%m/%d/%Y')
                a.save()

                sent_count += 1

    return JsonResponse({
        'status': 'success',
        'message': f'Successfully processed your request. Sent {sent_count} letter(s)'
    })

def event_signin_sheet(request, record_id):
    import pdfkit
    from cis.settings.pd_event import pd_event as pd_settings

    event = get_object_or_404(Event, pk=record_id)

    pd_templates = pd_settings.from_db()

    options = {
        'page-size': 'Letter'
    }

    base_template = 'pd_event/base.html'
    template = get_template(base_template)

    pd_template = pd_templates.get('event_signin_template', '')
    
    pd_template = Template(pd_template)
    pd_html = pd_template.render(Context({
       'cohort': event.cohorts,
       'term': event.term,
       'guest_list': event.guest_list_html,
       'start_date_time': timezone.localtime(event.start_time).strftime('%m/%d/%Y %H:%M'),
       'end_date_time': timezone.localtime(event.end_time).strftime('%m/%d/%Y %H:%M'),
       'event_type': event.event_type,
       'delivery_mode': event.delivery_mode
    }))

    html = template.render({'main_content': pd_html})
    
    pdf = pdfkit.from_string(html, False, options)

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="event_signin_sheet.pdf"'

    return response
event_signin_sheet.login_required = False

def pd_letter(request, attendance_id):
    import pdfkit
    from cis.settings.pd_event import pd_event as pd_settings

    attendee = get_object_or_404(EventAttendee, pk=attendance_id)

    pd_templates = pd_settings.from_db()

    options = {
        'page-size': 'Letter'
    }

    base_template = 'pd_event/base.html'
    template = get_template(base_template)

    pd_template = pd_templates.get('pd_template', '')

    attendee_info = attendee.get_info()
    pd_template = Template(pd_template)
    pd_html = pd_template.render(Context({
       'attendee_first_name': attendee_info.get('first_name'),
       'attendee_last_name': attendee_info.get('last_name'),
       'cohort': attendee.event.cohorts,
       'term': attendee.event.term,
       'earned_pd_hour': attendee.meta.get('pd_hour'),
       'start_date_time': timezone.localtime(attendee.event.start_time).strftime('%m/%d/%Y %H:%M'),
       'end_date_time': timezone.localtime(attendee.event.end_time).strftime('%m/%d/%Y %H:%M'),  
       'event_type': attendee.event.event_type,
       'pd_note': attendee.meta.get('note'),
       'delivery_mode': attendee.event.delivery_mode,
       'description': attendee.event.description
    }))

    html = template.render({'main_content': pd_html})
    pdf = pdfkit.from_string(html, False, options)

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="pd_letter.pdf"'

    return response
pd_letter.login_required = False

def export_attendee_list(request, record_id):
    event = Event.objects.get(id=record_id)

    file_name = 'event-attedee-list.csv'

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    writer = csv.writer(response)

    records = EventAttendee.objects.filter(
        event=event
    )
    
    fields = {
        'pk': 'ID',
        'term.academic_year.name': 'Academic Year',
        'term': "Term",
    }

    # Write Header
    writer.writerow([
        'Attendance Status',
        'Attendace Tyoe',
        'PD Hour/Attendees',
        'Note',
        'Type',
        'Name/Lastname',
        'Firstname',
        'Email',
        'Email 2',
        'Email 3',
    ])

    for a in records:
        row = []

        row.append(a.meta.get('attendance_status'))
        row.append(a.meta.get('attendance_type').replace('_', ' ').title())
        row.append(a.meta.get('pd_hour'))
        row.append(a.meta.get('note', ''))
        
        row.append(a.type.replace('_', ' ').title())

        if a.type == 'instructor':
            attendee = Teacher.objects.get(
                pk=a.meta['id']
            )
            row.append(attendee.user.last_name)
            row.append(attendee.user.first_name)
            row.append(attendee.user.email)
            row.append(attendee.user.alt_email)
            row.append(attendee.user.secondary_email)

        elif a.type == 'faculty':
            attendee = FacultyCoordinator.objects.get(
                pk=a.meta['id']
            )
            row.append(attendee.user.last_name)
            row.append(attendee.user.first_name)
            row.append(attendee.user.email)
        elif a.type == 'cohort_participant':
            attendee = CohortParticipant.objects.get(
                pk=a.meta['id']
            )
            row.append(attendee.user.last_name)
            row.append(attendee.user.first_name)
            row.append(attendee.user.email)
        elif a.type == 'highschool':
            attendee = HighSchool.objects.get(
                pk=a.meta['id']
            )
            row.append(attendee.name)
            
        writer.writerow(row)

    return response

def update_count(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendee = request.GET.get('attendee', None)
    key = request.GET.get('key', None)
    val = request.GET.get('val', None)

    attendee = EventAttendee.objects.get(
        event=event,
        id=attendee
    )
    attendee.meta[ key ] = val
    attendee.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def mark_attendance(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendees = request.POST.getlist('attendee', None)
    attendance_status = request.POST.get('attendance_status')

    attendees = EventAttendee.objects.filter(
        event=event,
        id__in=attendees
    )
    for a in attendees:
        a.meta['attendance_status'] = attendance_status
        if attendance_status == 'not attended':
            a.meta['pd_hour'] = 0
            a.meta['participants'] = 0
        a.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def add_attendee(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendees = request.POST.getlist('attendee', None)
    attendee_type = request.POST.get('type')
    attendance_type = request.POST.get('attendance_type')

    if not attendees:
        return JsonResponse({
            'status': 'error',
            'message': 'Please select a record and try again'})

    num_added = 0
    mesg = []
    for r in attendees:
        try:
            ea = EventAttendee(
                event=event
            )
            ea.type = attendee_type
            ea.meta = {
                'id': str(r)
            }
            
            ea.meta['attendance_type'] = attendance_type
            ea.meta['attendance_status'] = 'N/A'
            if ea.type == 'instructor' or ea.type == 'cohort_participant' or ea.type == 'faculty':
                ea.meta['pd_hour'] = event.pd_hour
            else:
                ea.meta['participants'] = 0

            ea.save()

            num_added += 1
        except Exception as e:
            print(e)
            pass

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def remove_attendee(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendees = request.POST.getlist('attendee', None)

    if not attendees:
        return JsonResponse({
            'status': 'error',
            'message': 'Please select a record and try again'})

    EventAttendee.objects.filter(
        id__in=attendees
    ).delete()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def send_reminder(request, record_id):
    
    from pd_event.forms import EventEmailForm

    event = Event.objects.get(id=record_id)
    if request.method == 'POST':
        ...
    
    form = EventEmailForm(event)

    template = 'pd_event/send_email.html'
    context = {
        'title': 'Send Email',
        'form': form,
        'status': 'display'
    }
    
    return render(request, template, context)
    # event.send_reminder_email()
    
    # note = EventNote(
    #     event=event,
    #     note='Sent event reminder email',
    #     createdby=request.user
    # )
    # note.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request, and added note.'
    })

def toggle_attendee(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'})

    event = Event.objects.get(id=record_id)
    attendees = request.POST.getlist('attendee', None)

    if not attendees:
        return JsonResponse({
            'status': 'error',
            'message': 'Please select a record and try again'})

    attendees = EventAttendee.objects.filter(
        id__in=attendees
    )
    for attendee in attendees:
        attendee.meta['attendance_type'] = 'required' if attendee.meta['attendance_type'] == 'optional' else 'optional'
        attendee.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def attendees(request, record_id):
    record = get_object_or_404(Event, pk=record_id)
    attendees = EventAttendee.objects.filter(
        event=record
    )

    result = {'data': []}
    for a in attendees:
        name = ''
        if a.type == 'instructor':
            try:
                attendee = Teacher.objects.get(
                    pk=a.meta['id']
                )
                name = f'{attendee.user.last_name}, {attendee.user.first_name}'
            except:
                continue
        elif a.type == 'faculty':
            attendee = FacultyCoordinator.objects.get(
                pk=a.meta['id']
            )
            name = f'{attendee.user.last_name}, {attendee.user.first_name}'
        elif a.type == 'cohort_participant':
            attendee = CohortParticipant.objects.get(
                pk=a.meta['id']
            )
            name = f'{attendee.user.last_name}, {attendee.user.first_name}'
        elif a.type == 'highschool':
            attendee = HighSchool.objects.get(
                pk=a.meta['id']
            )
            name = f'{attendee.name}'

        result['data'].append(
            {
                'id': a.id,
                'attendee_type': a.type.replace('_', ' ').title(),
                'name': name,
                'attendance_status': a.meta.get('attendance_status', '').title(),
                'attendance_type': a.meta.get('attendance_type').replace('_', ' ').title(),
                'pd_hour': a.meta.get('pd_hour'),
                'pd_letter_sent_on': a.meta.get('pd_letter_sent_on', '-'),
                'pd_letter': a.pd_url,
                'note': a.meta.get('note', ''),
                'participants': a.meta.get('participants'),
            }
        )
    return JsonResponse(result)

def get_courses(request):
    cohort = request.GET.get('cohort', '').split(',')

    courses = Course.objects.filter(
        cohort__id__in=cohort,
        status__iexact='active'
    )
    result = {
        'data': []
    }

    for course in courses:
        result['data'].append({
            'id': course.id,
            'name': f'{course.cohort.designator} {course.catalog_number}'
        })
    
    return JsonResponse(result)

def search_guest_list(request):
    attendee_type = request.GET.get('attendee_type')
    cohort = request.GET.getlist('cohort')
    course = request.GET.getlist('course')
    course_status = request.GET.getlist('instructor_course_status')
    since = request.GET.get('since')
    fac_assistant = request.GET.getlist('fac_assistant')

    result = {
        'data': []
    }

    if attendee_type == 'cohort_participant':
        p_ids = CohortAffiliation.objects.filter(
            cohort__id__in=cohort,
            status__iexact='active'
        ).values_list('cohort_participant__id', flat=True)
        
        records = CohortParticipant.objects.filter(
            id__in=p_ids
        ).order_by('user__last_name')

        for record in records:
            result['data'].append({
                'id': record.id,
                'name': f'{record.user.last_name}, {record.user.first_name}',
                'attendee_type': attendee_type
            })

    elif attendee_type == 'faculty':
        fac_ids = CourseAdministrator.objects.filter(
            course__cohort__id__in=cohort
        ).values_list('user__id', flat=True)

        records = FacultyCoordinator.objects.filter(
            status__iexact='active',
            user__id__in=fac_ids
        )
    
        records = records.order_by('user__last_name')


        for record in records:
            result['data'].append({
                'id': record.id,
                'name': f'{record.user.last_name}, {record.user.first_name}',
                'attendee_type': attendee_type
            })
    
    elif attendee_type == 'highschool':
        records = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')

        for record in records:
            result['data'].append({
                'id': record.id,
                'name': record.name,
                'attendee_type': attendee_type
            })

    elif attendee_type == 'instructor':
        teacher_ids = TeacherCourseCertificate.objects.filter(
            course__id__in=course,
            status__in=course_status
        )
        if since:
            since = datetime.datetime.strptime(since, '%m/%d/%Y')
            teacher_ids = teacher_ids.filter(
                since__gte=since
            )
        teacher_ids = teacher_ids.values_list('teacher_highschool__teacher__id', flat=True)

        records = Teacher.objects.filter(
            id__in=teacher_ids
        )
        
        for record in records:
            result['data'].append({
                'id': record.id,
                'name': f'{record.user.last_name}, {record.user.first_name}',
                'attendee_type': attendee_type
            })

    return JsonResponse(result)

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'pd_event/event.html'
    record = get_object_or_404(Event, pk=record_id)
    
    form = EventForm(instance=record)
    file_form = EventFileForm(event=record)
    email_form = EventEmailForm(record)
    email_after_form = EventEmailForm(record, 'send_email_after_event')

    if request.method == 'POST':
        if request.POST.get('action', '').startswith('send_email'):
            email_form = EventEmailForm(record, request.POST.get('action'), request.POST)

            if email_form.is_valid():
                email_form.save(request, record)

                return JsonResponse({
                    'status': 'success',
                    'message': 'Successfully sent email'
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please fix the error(s) and try again',
                    'errors': email_form.errors.as_json()
                }, status=400)


        if request.POST.get('action') == 'edit_event':
            form = EventForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False, request=request)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success')
                return redirect('pd_event:event', record_id=record_id)
        
        if request.POST.get('action') == 'edit_event_file':
            file_form = EventFileForm(record, request.POST, request.FILES)

            if file_form.is_valid():
                m = file_form.save(commit=True)    

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully added file',
                    'list-group-item-success')
                return redirect('pd_event:event', record_id=record_id)
    
    # notes = EventNote.objects.filter(
    #     event=record
    # )

    read_only = False
    if user_has_faculty_role(request.user):
        menu = draw_menu(FACULTY_MENU, 'events', 'pd_event_faculty:event')
        urls = {
            'all_items': 'pd_event_faculty:events'
        }
        read_only = True
    else:
        menu = draw_menu(cis_menu, 'events', 'event_list')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'all_items': 'pd_event:events'
        }

    return render(
        request,
        template, {
            'form': form,
            'file_form': file_form,
            'email_after_form': email_after_form,
            'attendee_form': EventAttendeeFilterForm(),
            'files': record.files(),
            'email_form': email_form,
            'page_title': "Event",
            'labels': {
                'all_items': 'All Events'
            },
            'urls': urls,
            'read_only': read_only,
            'menu': menu,
            # 'notes': notes,
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'pd_event/event-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = EventForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=True, request=request)

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
                'Successfully added event.',
                'list-group-item-success') 
            return redirect('pd_event:event', record_id=record.id)
        else:
            messages.add_message(
                request,
                messages.WARNING,
                'Please correct the error(s) and try again',
                'list-group-item-danger') 

        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = EventForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Events'
            },
            'urls': {
                'add_new': 'pd_event:event_add_new',
                'all_items': 'pd_event:events'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'event_list')
        })

def index(request):
    '''
     search and index page for staff
    '''
    if user_has_faculty_role(request.user):
        menu = draw_menu(FACULTY_MENU, 'events', 'pd_event_faculty:event')
        urls = {
            'all_items': 'pd_event_faculty:events',
            'details_prefix': '/ce/events/event/'
        }
    else:
        menu = draw_menu(cis_menu, 'events', 'event_list')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'details_prefix': '/ce/events/event/',
            'all_items': 'pd_event:event'
        }
    template = 'pd_event/event-list.html'
    return render(
        request,
        template, {
            'page_title': 'Events',
            'urls': urls,
            'menu': menu,
            'terms': Term.objects.all().order_by('-code'),
            'cohorts': Cohort.objects.all().order_by('name'),
            'event_types': EventType.objects.all().order_by('name'),
            'api_url': '/ce/events/api/events?format=datatables'
        }
    )

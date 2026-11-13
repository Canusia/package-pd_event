import datetime, os, logging, csv

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
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
from cis.highschool_scope import picker_queryset
from cis.models.term import Term
from cis.models.course import Cohort, CohortParticipant, CohortAffiliation, Course, CourseAdministrator
from cis.models.note import EventNote
from cis.models.teacher import (
    TeacherCourseCertificate,
    Teacher
)

from ..models import EventType, Event, EventFile, EventAttendee
from ..serializers import EventSerializer
from ..services.summary import track_cost
from ..forms import EventForm, EventFileForm, EventAttendeeFilterForm, EventEmailForm

from cis.menu import cis_menu, draw_menu, FACULTY_MENU

from cis.utils import CIS_user_only, user_has_faculty_role, FACULTY_user_only, user_has_cis_role

class EventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EventSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only]

    def get_queryset(self):
        records = Event.objects.all()

        if user_has_cis_role(self.request.user):
            ...
        elif user_has_faculty_role(self.request.user):
            try:
                records = records.filter(
                    courses__id__in=FacultyCoordinator.courses_overseeing(self.request.user).values_list('course__id', flat=True)
                )
            except Exception as e:
                print(e)
        
        if self.request.GET.get('term'):
            records = records.filter(
                term__code=self.request.GET.get('term')
            )
        if self.request.GET.get('event_type'):
            records = records.filter(
                event_type__id=self.request.GET.get('event_type')
            )

        if self.request.GET.get('course'):
            records = records.filter(
                courses__id=self.request.GET.get('course')
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

        # Guest counts for the list (#9). distinct: the course filter joins
        # the courses M2M, which would otherwise multiply the rows counted.
        from django.db.models import Count
        attendee_id = 'eventattendee__id'
        return records.select_related('event_type', 'term').annotate(
            att_invited=Count(attendee_id, distinct=True),
            att_attended=Count(attendee_id, distinct=True, filter=Q(
                eventattendee__meta__attendance_status__iexact='attended')),
            att_not_attended=Count(attendee_id, distinct=True, filter=Q(
                eventattendee__meta__attendance_status__iexact='not attended')),
        )

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

    from ..services.summary import gets_letter, letter_sent_on

    if request.POST.get('scope') == 'owed':
        # Everyone who attended and has not been sent a letter (#9).
        attendees = [a for a in EventAttendee.objects.filter(event=event)
                     if gets_letter(a) and not letter_sent_on(a)]
        if not attendees:
            return JsonResponse({
                'status': 'warning',
                'message': 'Every attendee who attended has already been sent a letter.'
            })
    else:
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
        if gets_letter(a):
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

    # Any guest type (#12); the same values as the PD letter email.
    pd_template = Template(pd_template)
    pd_html = pd_template.render(Context(attendee.letter_context()))

    html = template.render({'main_content': pd_html})
    pdf = pdfkit.from_string(html, False, options)

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="pd_letter.pdf"'

    return response
pd_letter.login_required = False

def export_attendee_list(request, record_id):
    event = Event.objects.get(id=record_id)

    file_name = 'event-attedee-list-' + datetime.datetime.now().strftime('%Y-%m-%d') + '.csv'

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
            
            row.append(a.course_certificate.teacher_highschool.teacher.user.last_name)
            row.append(a.course_certificate.teacher_highschool.teacher.user.first_name)
            row.append(a.course_certificate.teacher_highschool.teacher.user.email)
            row.append(a.course_certificate.teacher_highschool.teacher.user.alt_email)
            row.append(a.course_certificate.teacher_highschool.teacher.user.secondary_email)
            row.append(a.course_certificate.course.name)
            row.append(a.course_certificate.teacher_highschool.highschool.name)
            row.append(a.course_certificate.status)

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

    if request.POST.get('scope') == 'unmarked':
        # "Mark everyone still unmarked as not attended" (#9). Only that
        # direction: marking a whole list as attended must be a choice.
        if attendance_status != 'not attended':
            return JsonResponse({
                'status': 'error',
                'message': 'Only "Not Attended" can be applied to everyone unmarked.'
            }, status=400)
        from ..services.summary import KEY_NOT_MARKED, status_key
        attendees = [a for a in EventAttendee.objects.filter(event=event)
                     if status_key(a) == KEY_NOT_MARKED]
    else:
        attendees = EventAttendee.objects.filter(
            event=event,
            id__in=attendees
        )
    for a in attendees:
        a.meta['attendance_status'] = attendance_status
        if attendance_status == 'not attended':
            a.meta['pd_hour'] = 0
            a.meta['participants'] = 0
        elif attendance_status == 'attended' and a.type != 'highschool':
            # Not attended zeroed the hours; marking attended again (one
            # click since #9) gives back the event's hours. Hours CE typed
            # for this attendee are kept.
            try:
                hours = float(a.meta.get('pd_hour') or 0)
            except (TypeError, ValueError):
                hours = 0
            if not hours:
                a.meta['pd_hour'] = event.pd_hour
        a.save()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully processed your request'
    })

def add_attendee(request, record_id):
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please login to continue'
        })

    event = Event.objects.get(id=record_id)
    attendees = request.POST.getlist('attendee', None)
    attendee_type = request.POST.get('type') or 'instructor'
    attendance_type = request.POST.get('attendance_type')

    if attendee_type not in EventAttendee.PERSON_TYPES:
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown guest type.'
        })

    if not attendees:
        return JsonResponse({
            'status': 'error',
            'message': 'Please select a record and try again'
        })

    num_added = 0
    num_combined = 0

    # One row per person (#10): an instructor already on the list, or added
    # twice in this batch, gets the extra course noted on their row.
    from ..services.summary import courses_of, teacher_id
    by_teacher = {}
    if attendee_type == 'instructor':
        for row in EventAttendee.objects.filter(event=event, type='instructor').select_related(
                'course_certificate__course', 'course_certificate__teacher_highschool'):
            if teacher_id(row):
                by_teacher.setdefault(teacher_id(row), row)

    for r in attendees:

        try:
            cert = None
            if attendee_type == 'instructor':
                if EventAttendee.objects.filter(
                    course_certificate__certificate_id=r,
                    event=event
                ).exists():
                    continue
                cert = TeacherCourseCertificate.objects.select_related(
                    'course', 'teacher_highschool').get(certificate_id=r)
                existing = by_teacher.get(cert.teacher_highschool.teacher_id)
                if existing is not None:
                    courses = courses_of(existing)
                    if cert.course.name not in courses:
                        courses.append(cert.course.name)
                    existing.meta['courses'] = courses
                    existing.save()
                    num_combined += 1
                    continue
            elif EventAttendee.objects.filter(
                    event=event, type=attendee_type, meta__id=str(r)).exists():
                continue

            ea = EventAttendee(
                event=event
            )
            ea.type = attendee_type
            ea.meta = {
                'id': str(r)
            }

            if cert is not None:
                ea.course_certificate = cert
                ea.meta['courses'] = [cert.course.name]

            ea.meta['attendance_type'] = attendance_type
            ea.meta['attendance_status'] = 'N/A'
            if ea.type in EventAttendee.PERSON_TYPES:
                ea.meta['pd_hour'] = event.pd_hour
            else:
                ea.meta['participants'] = 0

            ea.save()
            if cert is not None:
                by_teacher[cert.teacher_highschool.teacher_id] = ea

            num_added += 1
        except Exception as e:
            logging.getLogger(__name__).warning('add_attendee %s: %s', r, e)

    message = f'Successfully processed your request: {num_added} added.'
    if num_combined:
        message += (f' {num_combined} course(s) noted on instructors already on the list'
                    ' (one row per person).')
    return JsonResponse({
        'status': 'success',
        'message': message
    })


def set_rsvp(request, record_id):
    """CE records an RSVP for the selected guests (#14); '' clears it."""
    if not (user_has_cis_role(request.user) or user_has_faculty_role(request.user)):
        raise PermissionDenied
    event = get_object_or_404(Event, pk=record_id)
    answer = request.POST.get('rsvp', '')
    ids = request.POST.getlist('attendee')
    if not ids:
        return JsonResponse({'status': 'error', 'message': 'Please select a record and try again'})
    rows = EventAttendee.objects.filter(event=event, id__in=ids)
    for row in rows:
        row.set_rsvp(answer, 'ce')
    label = {'confirmed': 'confirmed', 'declined': 'declined'}.get(answer, 'cleared')
    return JsonResponse({'status': 'success', 'message': f'RSVP {label} for {len(rows)} guest(s).'})


def rsvp(request, token):
    """The guest's RSVP page from the emailed link (#14). No login: the link
    is signed. Answers are taken until the event starts."""
    from django.http import Http404
    attendee = EventAttendee.from_rsvp_token(token)
    if attendee is None:
        return render(request, 'pd_event/rsvp.html', {'not_found': True}, status=404)
    event = attendee.event
    started = bool(event.start_time and event.start_time <= timezone.now())
    saved = False
    if request.method == 'POST' and not started:
        answer = request.POST.get('answer')
        if answer in EventAttendee.RSVP_CHOICES:
            attendee.set_rsvp(answer, 'guest')
            saved = True
    person = attendee.recipient() or {}
    return render(request, 'pd_event/rsvp.html', {
        'attendee': attendee, 'event': event, 'person': person,
        'answer': (attendee.meta or {}).get('rsvp', ''), 'started': started, 'saved': saved,
    })
rsvp.login_required = False


def merge_duplicates(request, record_id):
    """Merge Duplicate Invites on the guest list (#10)."""
    if not (user_has_cis_role(request.user) or user_has_faculty_role(request.user)):
        raise PermissionDenied
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST only.'}, status=405)
    from ..services.summary import merge_duplicates as merge
    removed = merge(get_object_or_404(Event, pk=record_id))
    if not removed:
        return JsonResponse({'status': 'success', 'message': 'No duplicate invites found.'})
    return JsonResponse({
        'status': 'success',
        'message': f'Merged {removed} duplicate invite(s): one row per person now.'
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
    from ..services import summary as att

    record = get_object_or_404(Event, pk=record_id)
    attendees = att.event_attendees(record)

    result = {'data': []}
    for a in attendees:
        name = ''
        col_2 = ''
        col_3 = ''
        if a.type == 'instructor':
            try:
                name = f'{a.course_certificate.teacher_highschool.teacher.user.last_name}, {a.course_certificate.teacher_highschool.teacher.user.first_name}'

                col_2 = ', '.join(att.courses_of(a))
                col_3 = f'{a.course_certificate.teacher_highschool.highschool.name}'
            except Exception:
                # Listed rather than skipped, so the table agrees with the
                # summary counts and can still be marked or removed (#9).
                name = '(instructor record missing)'
        elif a.type in ('faculty', 'cohort_participant', 'highschool_admin'):
            info = a.get_info()
            name = (f"{info.get('last_name')}, {info.get('first_name')}"
                    if info.get('attendee') else '(record missing)')
            if a.type == 'highschool_admin' and info.get('attendee'):
                col_2 = ', '.join(_personnel_schools(info['attendee']))
        elif a.type == 'highschool':
            attendee = HighSchool.objects.filter(pk=a.meta.get('id')).first()
            name = attendee.name if attendee else '(record missing)'

        school, course = att.school_and_course(a)
        key = att.status_key(a)
        result['data'].append(
            {
                'id': a.id,
                'attendee_type': a.get_type_display(),
                'attendee_type_key': a.type,
                'name': name,
                'col_2': col_2,
                'col_3': col_3,
                'school': school,
                'course': course,
                'courses': att.courses_of(a),
                'attendance_status': att.STATUS_LABELS[key],
                'status_key': key,
                'attendance_type': (a.meta.get('attendance_type') or '').replace('_', ' ').title(),
                'attendance_type_key': att.attendance_type_key(a),
                'required_missed': att.is_required_missed(a),
                'rsvp': att.rsvp_key(a),
                'pd_hour': a.meta.get('pd_hour'),
                'pd_letter_sent_on': att.letter_sent_on(a),
                'gets_letter': att.gets_letter(a),
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
    attendee_type = request.GET.get('attendee_type', 'instructor')
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
        # Course administrators of the chosen courses or subjects (#12).
        course = [c for c in course if c]
        fac_ids = CourseAdministrator.objects.filter(
            Q(course__cohort__id__in=[c for c in cohort if c]) | Q(course__id__in=course)
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
    
    elif attendee_type == 'highschool_admin':
        # High school personnel with an active position at the chosen
        # schools or districts (#12).
        from cis.models.highschool_administrator import HSAdministrator
        highschools = [h for h in request.GET.getlist('highschool') if h]
        districts = [d for d in request.GET.getlist('district') if d]
        if not (highschools or districts):
            return JsonResponse({
                'data': [],
                'message': 'Choose at least one high school or district.'
            })
        position_q = Q(hsadministratorposition__status__iexact='active')
        if highschools:
            position_q &= Q(hsadministratorposition__highschool__id__in=highschools)
        if districts:
            position_q &= Q(hsadministratorposition__highschool__district__id__in=districts)
        records = HSAdministrator.objects.filter(position_q).distinct().select_related(
            'user').order_by('user__last_name', 'user__first_name')
        for record in records:
            result['data'].append({
                'id': str(record.id),
                'name': f'{record.user.last_name}, {record.user.first_name}',
                'col_2': ', '.join(_personnel_schools(record)),
                'col_3': ', '.join(_personnel_positions(record)),
                'col_4': record.user.email,
                'col_5': '',
                'attendee_type': attendee_type
            })

    elif attendee_type == 'highschool':
        # Schools with an Active link to the current campus (per request).
        records = picker_queryset()

        for record in records:
            result['data'].append({
                'id': record.id,
                'name': record.name,
                'attendee_type': attendee_type
            })

    elif attendee_type == 'instructor':
        # Any mix of course, term taught, high school and district (#11), so
        # an event with no courses can still find its guests.
        teaching_term = request.GET.get('teaching_term')
        highschools = [h for h in request.GET.getlist('highschool') if h]
        districts = [d for d in request.GET.getlist('district') if d]
        course = [c for c in course if c]
        if not (course or teaching_term or highschools or districts):
            return JsonResponse({
                'data': [],
                'message': 'Choose at least one course, term, high school or district.'
            })

        from django.db.models.functions import Lower
        records = TeacherCourseCertificate.objects.annotate(
            status_lower=Lower('status')
        ).filter(
            status_lower__in=[s.lower() for s in course_status]
        ).select_related('teacher_highschool__teacher__user',
                         'teacher_highschool__highschool', 'course')
        if course:
            records = records.filter(course__id__in=course)
        if highschools:
            records = records.filter(teacher_highschool__highschool__id__in=highschools)
        if districts:
            records = records.filter(teacher_highschool__highschool__district__id__in=districts)
        if teaching_term:
            records = records.filter(_teaches_in_term(teaching_term))
        if since:
            since = datetime.datetime.strptime(since, '%m/%d/%Y')
            records = records.filter(
                since__gte=since
            )
        
        for record in records:
            result['data'].append({
                'id': record.certificate_id,
                'name': f'{record.teacher_highschool.teacher.user.last_name}, {record.teacher_highschool.teacher.user.first_name}',
                'col_2': f'{record.teacher_highschool.highschool.name}',
                'col_3': f'{record.course.name}',
                'col_4': f'{record.status}',
                'col_5': f'{record.since}',
                'attendee_type': attendee_type
            })

    return JsonResponse(result)

def _active_positions(hsadmin):
    from cis.models.highschool_administrator import HSAdministratorPosition
    return HSAdministratorPosition.objects.filter(
        hsadmin=hsadmin, status__iexact='active').select_related('highschool', 'position')


def _personnel_schools(hsadmin):
    return sorted({p.highschool.name for p in _active_positions(hsadmin)})


def _personnel_positions(hsadmin):
    return sorted({p.position.name for p in _active_positions(hsadmin)})


def _teaches_in_term(term_id):
    """Q for certificates whose teacher teaches that course in the term, as
    the primary or (cis with #154) a secondary teacher of a section."""
    from django.db.models import Exists, OuterRef
    from cis.models.section import ClassSection

    sections = ClassSection.objects.filter(
        term_id=term_id, course_id=OuterRef('course_id'))
    q = Q(Exists(sections.filter(teacher_id=OuterRef('teacher_highschool__teacher_id'))))
    try:
        from cis.models.section_secondary import ClassSectionSecondaryTeacher
    except ImportError:  # cis before #154
        return q
    secondary = ClassSectionSecondaryTeacher.objects.filter(
        class_section__term_id=term_id, class_section__course_id=OuterRef('course_id'),
        teacher_id=OuterRef('teacher_highschool__teacher_id'))
    return q | Q(Exists(secondary))


@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'pd_event/event.html'
    record = get_object_or_404(Event, pk=record_id)
    
    form = EventForm(request, instance=record)
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
            form = EventForm(request, request.POST, instance=record)

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
    
    notes = EventNote.objects.filter(
        event=record
    )

    read_only = False
    if user_has_cis_role(request.user):
        menu = draw_menu(cis_menu, 'events', 'event_list', 'ce')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'all_items': 'pd_event:events'
        }
    elif user_has_faculty_role(request.user):
        menu = draw_menu(FACULTY_MENU, 'events', 'pd_event_faculty:event', 'faculty')
        urls = {
            'all_items': 'pd_event_faculty:events'
        }
        # read_only = True
    else:
        raise PermissionDenied

    return render(
        request,
        template, {
            'form': form,
            'file_form': file_form,
            'email_after_form': email_after_form,
            'attendee_form': EventAttendeeFilterForm(event=record),
            'files': record.files(),
            'email_form': email_form,
            'page_title': "Event",
            'labels': {
                'all_items': 'All Events'
            },
            'urls': urls,
            'read_only': read_only,
            'menu': menu,
            'notes': notes,
            'summary': event_summary(record),
            # A failed save shows the form again, with its errors (#13).
            'edit_open': request.method == 'POST' and request.POST.get('action') == 'edit_event',
            'track_cost': track_cost(),
            'record': record
        })



def event_summary(record):
    from ..services.summary import event_summary as summarize_event
    return summarize_event(record)


def event_summary_view(request, record_id):
    """The summary cards alone, re-fetched after attendance changes (#9)."""
    record = get_object_or_404(Event, pk=record_id)
    if not (user_has_cis_role(request.user) or user_has_faculty_role(request.user)):
        raise PermissionDenied
    return render(request, 'pd_event/_event_summary.html', {
        'summary': event_summary(record), 'record': record})


def _ce_only(request):
    if not user_has_cis_role(request.user):
        raise PermissionDenied


def events_by_term(request):
    """The By Term tab on the events list: one row per term (#9)."""
    _ce_only(request)
    from ..services.summary import by_term
    return JsonResponse({'data': by_term()})


def events_by_term_detail(request, term_id):
    """A term's breakdowns and events, for the By Term drill-down."""
    _ce_only(request)
    from ..services.summary import term_detail
    return JsonResponse(term_detail(get_object_or_404(Term, pk=term_id)))


def required_missed_csv(request, term_id):
    """Instructors marked Not Attended on a required event in the term."""
    _ce_only(request)
    from ..services.summary import person, required_missed, school_and_course
    term = get_object_or_404(Term, pk=term_id)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="required-missed-{term.code}.csv"')
    writer = csv.writer(response)
    writer.writerow(['Last Name', 'First Name', 'Email', 'High School', 'Course',
                     'Event', 'Event Type', 'Event Date'])
    def cell(value):
        # Spreadsheet apps run a cell that starts with = + - @ as a formula.
        value = '' if value is None else str(value)
        return "'" + value if value[:1] in ('=', '+', '-', '@') else value

    for a in required_missed(term):
        school, course = school_and_course(a)
        event = a.event
        writer.writerow([cell(v) for v in [
            *person(a), school, course, event.name or '', event.event_type.name,
            event.start_time_local.strftime('%m/%d/%Y') if event.start_time else '',
        ]])
    return response

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'pd_event/event-add_new.html'
    ajax = request.GET.get('ajax', None)
    
    if user_has_cis_role(request.user):
        menu = draw_menu(cis_menu, 'events', 'event_list', 'ce')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'details_prefix': '/ce/events/event/',
            'all_items': 'pd_event:event'
        }
    elif user_has_faculty_role(request.user):
        menu = draw_menu(FACULTY_MENU, 'events', 'pd_event_faculty:event', 'faculty')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'all_items': 'pd_event_faculty:events',
            'details_prefix': '/faculty/events/event/'
        }
    else:
        raise PermissionDenied

    if request.method == 'POST':
        form = EventForm(request, request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=True, request=request)

            data = {
                'status':'success',
                'message':'Successfully added event. Click "Ok" to continue.',
                'action': 'redirect_to',
                'redirect_to': record.ce_url if user_has_cis_role(request.user) else record.faculty_url
            }
            return JsonResponse(data)
        else:
            return JsonResponse({
                'message': 'Please correct the errors and try again',
                'errors': form.errors.as_json()
            }, status=400)
    else:
        form = EventForm(request)

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
            'menu': menu
        })

def delete(request, record_id):
    record = get_object_or_404(Event, pk=record_id)

    try:
        EventFile.objects.filter(
            event=record
        ).delete()

        EventAttendee.objects.filter(
            event=record
        ).delete()

        # print(type(record))
        EventNote.objects.filter(
            event=record
        ).delete()
        
        record.delete()

        messages.add_message(
            request,
            messages.SUCCESS,
            'Successfully deleted record',
            'list-group-item-success')
    except Exception as e:
        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error deleting the record. ' + str(e),
            'list-group-item-success')
        return redirect("pd_event:event", record_id=record.id)

    return redirect("pd_event:events")

def index(request):
    '''
     search and index page for staff
    '''
    if user_has_cis_role(request.user):
        menu = draw_menu(cis_menu, 'events', 'event_list', 'ce')
        urls = {
            'add_new': 'pd_event:event_add_new',
            'details_prefix': '/ce/events/event/',
            'all_items': 'pd_event:event'
        }
    elif user_has_faculty_role(request.user):
        menu = draw_menu(FACULTY_MENU, 'events', 'pd_event_faculty:event', 'faculty')
        urls = {
            'add_new': 'pd_event_faculty:event_add_new',
            'all_items': 'pd_event_faculty:events',
            'details_prefix': '/faculty/events/event/'
        }
    else:
        raise PermissionDenied

    template = 'pd_event/event-list.html'
    return render(
        request,
        template, {
            'page_title': 'Events',
            'urls': urls,
            'menu': menu,
            'terms': Term.objects.all().order_by('-code'),
            'courses': Course.objects.all().order_by('name'),
            'event_types': EventType.objects.all().order_by('name'),
            'api_url': '/ce/events/api/events?format=datatables',
            # The By Term tab reads CE-only endpoints (#9).
            'show_by_term': user_has_cis_role(request.user),
        }
    )

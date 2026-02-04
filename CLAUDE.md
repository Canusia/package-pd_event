# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Manages Professional Development events and high school information sessions. Tracks attendance, generates PD certificates/letters, and handles info session RSVPs.

## Key Components

### Models (`models.py`)
- **EventType** - Event categories (workshops, seminars, etc.)
- **Venue** - Physical locations with address details
- **Event** - PD events with timing, courses, PD hours, cost tracking
- **EventFile** - File attachments using private storage
- **EventAttendee** - Attendance records linked to TeacherCourseCertificate
- **InfoSession** - HS information sessions with multiple event dates
- **InfoSessionAttendee** - RSVP records with course interests

### URL Structure
**CE Routes** (`/ce/events/`):
- Event CRUD, attendee management, PD letters, sign-in sheets
- Info session management with RSVP tracking

**Faculty Routes** (`/faculty/events/`):
- Limited view for faculty-related events

**Public Routes** (`/info_session/`):
- `start_rsvp/<id>/` - Public RSVP form
- `submit_info_session_courses/<id>/` - Course interest selection

## Key Features

**PD Letters:** Generate certificates via `pd_letter` view, email via `email_pd_letter`.

**Sign-in Sheets:** PDF generation via `event_signin_sheet` for attendance tracking.

**Attendance Marking:** Toggle attended/not attended status with `mark_attendance`.

**Reminder Emails:** Send event reminders via `send_reminder`.

**Exports:** Attendee lists to CSV/Excel via `export_attendee_list`.

## Configuration

Via `pd_event` settings form:
- `track_pd_event_cost` - Toggle cost tracking
- `event_reminder_subject/template` - Reminder email config
- `event_signin_template` - Sign-in sheet HTML
- `pd_template` - PD certificate HTML
- `pd_email_subject/template` - PD letter email config

Template variables: `{{attendee_first_name}}`, `{{event_type}}`, `{{term}}`, `{{pd_hour}}`, `{{delivery_mode}}`

## Reports
- `pd_events` - Export events with filters
- `teacher_event_export` - Teacher attendance data

## Integration

- **Attendees:** Links to `cis.TeacherCourseCertificate` for teacher credentials
- **Courses:** M2M with `cis.Course` for event topics
- **Terms:** FK to `cis.Term` for academic period
- **Cohorts:** JSONField for cohort-based filtering via `cis.CohortParticipant`
- **Files:** Uses `PrivateMediaStorage` for attachments
- **PDF:** Generated via `pdfkit`

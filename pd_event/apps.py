from django.apps import AppConfig


class PdEventConfig(AppConfig):
    name = 'pd_event'

    CONFIGURATORS = [
        {
            'app': 'pd_event',
            'name': 'pd_event',
            'title': 'PD Event Settings',
            'description': '-',
            'categories': [
                '4'
            ]
        },
    ]

    REPORTS = [
        {
            'app': 'pd_event',
            'name': 'pd_events',
            'title': 'PD Events - Export',
            'description': '-',
            'categories': [
                'Instructors'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'app': 'pd_event',
            'name': 'teacher_event_export',
            'title': 'PD Events - Teacher Export',
            'description': '-',
            'categories': [
                'Instructors'
            ],
            'available_for': [
                'ce'
            ]
        },
    ]
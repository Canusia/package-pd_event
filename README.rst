MyCE - PD Event
====================

- Setup

In settings.py, add the app to INSTALLED_APPS as 
'pd_event.apps.PdEventConfig'

In myce.urls.py
- path('ce/events/', include('pd_event.urls.ce')),
- path('faculty/events/', include('pd_event.urls.faculty')),


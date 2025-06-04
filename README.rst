MyCE - PD Event
====================

- Setup

In settings.py, add the app to INSTALLED_APPS as 
'pd_event.apps.PdEventConfig'

# Add this to the STATICFILES_DIRS
    os.path.join(get_package_path("pd_event"), 'staticfiles') if get_package_path("pd_event") else None,

# if get_package_path is not defined, you can use the following function to get the package path:
import importlib.util
def get_package_path(package_name):
    """Dynamically find package installation path."""
    spec = importlib.util.find_spec(package_name)
    return os.path.dirname(spec.origin) if spec else None


In myce.urls.py
- path('ce/events/', include('pd_event.urls.ce')),
- path('faculty/events/', include('pd_event.urls.faculty')),



"""Events sidebar section (cis.menu_registry); the 100 of the ce menu.

On a cis without the registry nothing registers.
"""
try:
    from cis.menu_registry import menu
except ImportError:   # cis without the registry: the menu migrations still apply
    menu = None

if menu is not None:
    menu.section('ce', 'events', 'Events', 'fas fa-fw fa-box', order=100)
    menu.register('ce', 'event_list', 'Events', url='pd_event:events',
                  parent='events', order=10)
    menu.register('ce', 'event_types', 'Event Types', url='pd_event:event_types',
                  parent='events', order=20)

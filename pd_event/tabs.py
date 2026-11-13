"""pd_event tabs on other apps' pages (#15).

Eager-imported from the app config's ready(). Each registry is optional: a
host without it skips the tab.
"""
import importlib
import importlib.util


def _registry(module, name):
    try:
        if importlib.util.find_spec(module) is None:
            return None
    except (ModuleNotFoundError, ValueError):
        return None
    return getattr(importlib.import_module(module), name, None)


def _register(target, *args, **kwargs):
    if target is None:
        return lambda fn: fn
    return target.tab(*args, **kwargs)


teacher_tabs = _registry('myce.component_registry.teacher', 'teacher_tabs')


@_register(teacher_tabs, slug='pd_events', title='PD Events', order=75,
           template='pd_event/tabs/_teacher_pd.html')
def teacher_pd_tab(request, record):
    """The CE instructor page: PD events across all their course certificates,
    hours earned and required events missed per term."""
    from .services.summary import teacher_history
    return {'history': teacher_history(record)}

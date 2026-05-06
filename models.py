# Compatibility shim: allows ``from pd_event.models import …`` to work when
# the editable submodule layout (pd_event/pd_event/) is active on sys.path.
from pd_event.pd_event.models import *  # noqa: F401, F403
from pd_event.pd_event.models import (  # noqa: F401 — explicit for IDE / static analysis
    Event,
    EventAttendee,
    EventFile,
    EventType,
)

"""Moved to memorychecks.store - Memory Checks is now a standalone library (memorychecks/).
This alias keeps old imports working: it IS that module, not a copy."""
import sys

import memorychecks.store as _impl

sys.modules[__name__] = _impl

"""Moved to memorychecks.langgraph_store - Memory Checks is now a standalone library (memorychecks/).
This alias keeps old imports working: it IS that module, not a copy."""
import sys

import memorychecks.langgraph_store as _impl

sys.modules[__name__] = _impl

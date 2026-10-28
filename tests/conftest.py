"""Test configuration.

The property-checked invariants (tests/test_invariants.py) explore random inputs on every local run.
On CI (GitHub sets CI=true) they run with a fixed seed instead, so the badge is reproducible: the same
hundreds of generated inputs are checked on every push, and any failure can be replayed exactly.
"""
import os

try:
    from hypothesis import settings
except ImportError:  # hypothesis is in requirements.txt; without it only the invariant tests are skipped
    settings = None

if settings is not None:
    settings.register_profile("ci", derandomize=True, print_blob=True)
    if os.environ.get("CI"):
        settings.load_profile("ci")

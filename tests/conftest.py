"""Test configuration.

The property-checked invariants (tests/test_invariants.py) explore random inputs on every local run.
On CI (GitHub sets CI=true) they run with a fixed seed instead, so the badge is reproducible: the same
hundreds of generated inputs are checked on every push, and any failure can be replayed exactly.
"""
import os

from hypothesis import settings

settings.register_profile("ci", derandomize=True, print_blob=True)
if os.environ.get("CI"):
    settings.load_profile("ci")

"""Selects the read backend.

THINGS_MCP_BACKEND=applescript (default) Apple Events via JXA; needs no filesystem
                               access, so it works under macOS 27's TCC rules.
THINGS_MCP_BACKEND=sqlite      things.py reads the Things database directly. Richer
                               (headings, checklists, reminders) but needs the server
                               process to hold access to Things' Group Container.
"""
import os

BACKEND = os.environ.get("THINGS_MCP_BACKEND", "applescript").strip().lower()
if BACKEND not in ("applescript", "sqlite"):
    raise RuntimeError(f"THINGS_MCP_BACKEND must be 'applescript' or 'sqlite', got {BACKEND!r}")

# The scripting dictionary exposes no headings, checklist items or reminder times.
SUPPORTS_STRUCTURE = BACKEND == "sqlite"

if BACKEND == "sqlite":
    import things  # noqa: F401
else:
    from . import as_reader as things

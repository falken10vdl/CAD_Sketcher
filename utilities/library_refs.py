"""Libraries saved before a body's sketch link could survive a library override.

A body's ``slvs:body_of`` link is kept on an override only when the body, in the
file that owns it, has the property flagged overridable. A library saved without
that flag makes every override of its bodies fall back to the linked sketch
after the file is saved and reopened.

Nothing here edits a file other than the one that is open: a main file reports
which libraries are outdated, and the repair runs in the library file itself.
"""

import os
from typing import List

import bpy

from .body import BODY_SKETCH_PATH, is_body


def body_link_is_overridable(body: bpy.types.Object) -> bool:
    try:
        return bool(body.is_property_overridable_library(BODY_SKETCH_PATH))
    except (TypeError, RuntimeError):
        return True


def outdated_libraries() -> List[bpy.types.Library]:
    """Libraries whose bodies are overridden here without the link flag.

    A body that is linked but never overridden is left out: nothing is lost
    until an override exists.
    """
    overridden = {
        obj.override_library.reference
        for obj in bpy.data.objects
        if obj.override_library is not None
        and obj.override_library.reference is not None
    }
    found = {}
    for obj in overridden:
        if obj.library is None or not is_body(obj):
            continue
        if not body_link_is_overridable(obj):
            found[obj.library.as_pointer()] = obj.library
    return sorted(found.values(), key=lambda lib: lib.filepath)


def outdated_body_objects() -> List[bpy.types.Object]:
    """This file's own bodies that lack the link flag: what a repair would touch."""
    return [
        obj
        for obj in bpy.data.objects
        if obj.library is None
        and obj.override_library is None
        and is_body(obj)
        and not body_link_is_overridable(obj)
    ]


def repair_blocker() -> str:
    """Why this file cannot be repaired and kept so, or an empty string.

    The repair only changes this file in memory; it does nothing until the file
    is saved, so a file that cannot be written would only look repaired.
    """
    path = bpy.data.filepath
    if path and os.path.exists(path) and not os.access(path, os.W_OK):
        return "This file is read-only. Save a writable copy first."
    return ""


def repair_bodies() -> int:
    """Flag this file's own bodies. Returns how many changed. Touches nothing else."""
    bodies = outdated_body_objects()
    for body in bodies:
        body.property_overridable_library_set(BODY_SKETCH_PATH, True)
    return len(bodies)


def library_label(library: bpy.types.Library) -> str:
    return bpy.path.basename(library.filepath) or library.name


def warning_lines(libraries) -> List[str]:
    names = sorted(library_label(lib) for lib in libraries)
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f" and {len(names) - 3} more"
    return [
        f"Saved by an older CAD Sketcher: {shown}",
        "Overridden sketches from it lose their workplane and body links",
        "when this file is saved and reopened.",
        "To fix: open the library file, run Repair Library File",
        "in the Sketcher panel, save it, then reload this file.",
    ]

"""Libraries saved before an object link could survive a library override.

A body's ``slvs:body_of`` link and a face workplane's ``slvs_wp_source`` link are
kept on an override only when the object, in the file that owns it, has the
property flagged overridable. A library saved without that flag makes every
override of such an object fall back to the linked object after the file is
saved and reopened.

Nothing here edits a file other than the one that is open: a main file reports
which libraries are outdated, and the repair runs in the library file itself.
"""

import os
from typing import List

import bpy

from .body import BODY_SKETCH_PATH, is_body
from .face_anchor import KEY_SOURCE, WP_SOURCE_PATH


def body_link_is_overridable(body: bpy.types.Object) -> bool:
    return _path_is_overridable(body, BODY_SKETCH_PATH)


def _path_is_overridable(obj: bpy.types.Object, path: str) -> bool:
    try:
        return bool(obj.is_property_overridable_library(path))
    except (TypeError, RuntimeError):
        return True


def unflagged_links(obj: bpy.types.Object) -> List[str]:
    """Paths of the object links ``obj`` stores that a library override would drop."""
    links = []
    if is_body(obj):
        links.append(BODY_SKETCH_PATH)
    if isinstance(obj.get(KEY_SOURCE), bpy.types.Object):
        links.append(WP_SOURCE_PATH)
    return [path for path in links if not _path_is_overridable(obj, path)]


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
        if obj.library is None:
            continue
        if unflagged_links(obj):
            found[obj.library.as_pointer()] = obj.library
    return sorted(found.values(), key=lambda lib: lib.filepath)


def outdated_body_objects() -> List[bpy.types.Object]:
    """This file's own objects that lack a link flag: what a repair would touch."""
    return [
        obj
        for obj in bpy.data.objects
        if obj.library is None and obj.override_library is None and unflagged_links(obj)
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
    """Flag this file's own objects. Returns how many changed. Touches nothing else."""
    objects = outdated_body_objects()
    for obj in objects:
        for path in unflagged_links(obj):
            obj.property_overridable_library_set(path, True)
    return len(objects)


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

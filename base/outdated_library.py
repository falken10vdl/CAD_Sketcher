"""One-shot warning when a linked library is outdated, shown after a file loads.

Follows ``whats_new``: an app timer defers the pop-up until the window exists,
and nothing runs in background mode. The panel keeps the same warning on screen
once the pop-up is dismissed.
"""

import logging

import bpy
from bpy.types import Operator

from ..declarations import Operators

logger = logging.getLogger(__name__)

_POPUP_WIDTH = 520
_FIRST_INTERVAL = 1.0


class VIEW3D_OT_slvs_outdated_library_warning(Operator):
    """Say which linked library was saved by an older CAD Sketcher"""

    bl_idname = Operators.OutdatedLibraryWarning
    bl_label = "CAD Sketcher: Outdated Library"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        from ..utilities.library_refs import outdated_libraries, warning_lines

        self._lines = warning_lines(outdated_libraries())
        return context.window_manager.invoke_popup(self, width=_POPUP_WIDTH)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Linked library is outdated", icon="ERROR")
        col = layout.column(align=True)
        for line in self._lines:
            col.label(text=line)

    def execute(self, context):
        return {"FINISHED"}


def _in_background() -> bool:
    return bpy.app.background


def _show():
    bpy.ops.view3d.slvs_outdated_library_warning("INVOKE_DEFAULT")


def _maybe_show():
    from ..utilities.library_refs import outdated_libraries

    if _in_background() or not outdated_libraries():
        return None
    try:
        _show()
    except Exception as e:
        logger.warning("Could not show the outdated library warning: %s", e)
    return None


def schedule_warning():
    if _in_background() or bpy.app.timers.is_registered(_maybe_show):
        return
    bpy.app.timers.register(_maybe_show, first_interval=_FIRST_INTERVAL)


def register():
    bpy.utils.register_class(VIEW3D_OT_slvs_outdated_library_warning)
    schedule_warning()


def unregister():
    if bpy.app.timers.is_registered(_maybe_show):
        bpy.app.timers.unregister(_maybe_show)
    bpy.utils.unregister_class(VIEW3D_OT_slvs_outdated_library_warning)

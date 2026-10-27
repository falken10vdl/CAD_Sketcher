"""Make this file safe to link from: flag its bodies so overrides keep their links."""

from bpy.types import Context, Operator
from bpy.utils import register_classes_factory

from ..declarations import Operators
from ..utilities.library_refs import (
    outdated_body_objects,
    repair_blocker,
    repair_bodies,
)


class View3D_OT_slvs_repair_library(Operator):
    """Mark this file's bodies so overrides of them keep their sketch links

    Run it in the library file itself, then save that file and reload the files
    that link it. It changes only this file's own bodies, in memory, and does
    not save."""

    bl_idname = Operators.RepairLibrary
    bl_label = "Repair Library File"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context):
        return bool(outdated_body_objects())

    def execute(self, context: Context):
        blocker = repair_blocker()
        if blocker:
            self.report({"WARNING"}, blocker)
            return {"CANCELLED"}
        count = repair_bodies()
        self.report({"INFO"}, f"Repaired {count} body/bodies. Save this file now.")
        return {"FINISHED"}


register, unregister = register_classes_factory((View3D_OT_slvs_repair_library,))

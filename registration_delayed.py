# Use a bpy.app.timer to register stuff that needs a valid context which isn't available during the normal registration

import bpy

from . import assets_manager, global_data


def startup_cb(*args):
    bpy.ops.view3d.slvs_register_draw_cb()
    assets_manager.load()
    return None


def register():
    bpy.app.timers.register(startup_cb, first_interval=1, persistent=True)


def unregister():
    # The startup timer may not have fired yet (add-on disabled right after
    # enabling); cancel it so it can't call the draw-callback operator after
    # the operators are gone.
    if bpy.app.timers.is_registered(startup_cb):
        bpy.app.timers.unregister(startup_cb)

    # Remove every viewport draw handler the startup callback added. Leaving any
    # of them registered makes them fire after the model properties are gone
    # (e.g. Scene.sketcher), spamming AttributeErrors on the next redraw.
    for attr in (
        "draw_handle",
        "hover_draw_handle",
        "icon_draw_handle",
        "origin_label_draw_handle",
    ):
        handle = getattr(global_data, attr, None)
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            setattr(global_data, attr, None)

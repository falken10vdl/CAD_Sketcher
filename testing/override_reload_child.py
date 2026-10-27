"""Blender-side steps of the override reload tests, run as separate processes.

``blender -b --factory-startup --python override_reload_child.py -- <step> ...``
where ``<step>`` is one of:

- ``library <package> <path> [old]``: write a library holding one part. With
  ``old`` the body's sketch link is left unflagged, as older versions saved it.
- ``override <package> <library> <main>``: link the library, override the part
  and save the result.
- ``report <package> <main>``: open the file and print one ``RESULT`` line of
  JSON describing what each local override still points at.
"""

import importlib
import json
import sys

import addon_utils
import bpy
from mathutils import Matrix


def _module(package, name):
    return importlib.import_module(f"{package}.{name}")


def _kind(value):
    if not isinstance(value, bpy.types.ID):
        return None
    if value.library is not None:
        return "linked"
    return "override" if value.override_library is not None else "local"


def make_library(package, path, old):
    context = bpy.context
    scene = context.scene
    body_mod = _module(package, "utilities.body")
    add_sketch = _module(package, "operators.add_sketch")
    curve_ref = _module(package, "model.curve_ref")

    scene.sketcher.entities.ensure_origin_elements(context)
    plane = add_sketch.new_workplane_empty(context, Matrix.Identity(4))
    sketch = add_sketch.build_sketch_on_workplane(context, plane)
    start = curve_ref.PointRef.create(sketch, (0, 0), fixed=True)
    end = curve_ref.PointRef.create(sketch, (1, 0))
    curve_ref.LineRef.create(sketch, start, end)
    sketch_obj = sketch.target_object
    body = body_mod.body_of(sketch_obj)
    if old:
        body.property_overridable_library_set(f'["{body_mod.BODY_SKETCH_KEY}"]', False)
    bpy.data.libraries.write(path, {sketch_obj, plane, body}, fake_user=True)


def make_override(package, library, main):
    scene = bpy.context.scene
    body_mod = _module(package, "utilities.body")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    with bpy.data.libraries.load(library, link=True) as (src, dst):
        dst.objects = list(src.objects)
    for obj in dst.objects:
        scene.collection.objects.link(obj)
    body = next(obj for obj in dst.objects if body_mod.is_body(obj))
    body.override_hierarchy_create(scene, bpy.context.view_layer)
    bpy.ops.wm.save_as_mainfile(filepath=main)


def report(package, main):
    body_mod = _module(package, "utilities.body")
    bpy.ops.wm.open_mainfile(filepath=main)
    result = {}
    for obj in bpy.data.objects:
        if obj.override_library is None or obj.library is not None:
            continue
        entry = {
            "workplane": _kind(obj.slvs_workplane),
            "body": _kind(obj.slvs_body),
        }
        if body_mod.is_body(obj):
            entry["body_of"] = _kind(obj.get(body_mod.BODY_SKETCH_KEY))
        result[obj.name] = entry
    print("RESULT " + json.dumps(result))


def main():
    step, package, *args = sys.argv[sys.argv.index("--") + 1 :]
    addon_utils.enable(package, default_set=True)
    if step == "library":
        make_library(package, args[0], len(args) > 1 and args[1] == "old")
    elif step == "override":
        make_override(package, args[0], args[1])
    elif step == "report":
        report(package, args[0])


main()

"""A library saved before the body link was flagged is reported, and repairable.

Reported where it is linked, repaired only in the file that owns the bodies.
"""

import os
import tempfile
from unittest import mock

import bmesh
import bpy

from ..base import outdated_library
from ..model.curve_ref import LineRef, PointRef
from ..operators import repair_library
from ..operators.add_sketch import build_sketch_on_workplane, create_face_workplane
from ..ui.panels import sketch_select
from ..utilities import library_refs
from ..utilities.body import BODY_SKETCH_PATH, body_of, ensure_body
from ..utilities.curve_data import refresh_curve_geometry
from ..utilities.face_anchor import WP_SOURCE_PATH
from ..utilities.workplane import ensure_origin_workplane_empties
from .test_override_reference_persistence import _run
from .utils import BgsTestCase


def flagged(body):
    return body.is_property_overridable_library(BODY_SKETCH_PATH)


class OutdatedLibraryCase(BgsTestCase):
    def setUp(self):
        super().setUp()
        existing = set(bpy.data.objects)
        self.addCleanup(
            lambda: bpy.data.batch_remove(
                [o for o in bpy.data.objects if o not in existing]
            )
        )
        self.entities.ensure_origin_elements(self.context)
        ensure_origin_workplane_empties(self.context)
        sketch = build_sketch_on_workplane(
            self.context, self.context.scene.sketcher.wp_xy
        )
        points = [PointRef.create(sketch, c) for c in ((0, 0), (4, 0), (4, 4))]
        LineRef.create(sketch, points[0], points[1])
        LineRef.create(sketch, points[1], points[2])
        refresh_curve_geometry(sketch)
        obj = sketch.target_object
        self.body = body_of(obj) or ensure_body(self.context, obj, "Body")

    def face_workplane(self):
        mesh = bpy.data.meshes.new("plate")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(mesh)
        bm.free()
        plate = bpy.data.objects.new("plate", mesh)
        self.context.scene.collection.objects.link(plate)
        top = next(p.index for p in mesh.polygons if p.normal.z > 0.9)
        return create_face_workplane(self.context, plate, top)

    def linked_part(self, outdated, override=True):
        """The body of a part linked from a library file, and its override."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "library.blend")
        _run("library", path, *(["old"] if outdated else []))
        before = set(bpy.data.objects)
        with bpy.data.libraries.load(path, link=True) as (src, dst):
            dst.objects = list(src.objects)
        scene = self.context.scene
        for obj in dst.objects:
            scene.collection.objects.link(obj)
        linked = next(obj for obj in dst.objects if "slvs:body_of" in obj)
        if override:
            linked.override_hierarchy_create(scene, self.context.view_layer)
        added = [obj for obj in bpy.data.objects if obj not in before]
        self.addCleanup(
            lambda: bpy.data.batch_remove(
                [obj for obj in added if obj.name in bpy.data.objects]
                + [linked.library]
            )
        )
        overrides = [o for o in added if o.override_library and "slvs:body_of" in o]
        return linked, (overrides[0] if overrides else None)


class TestDetection(OutdatedLibraryCase):
    def test_a_body_made_now_is_flagged(self):
        self.assertTrue(flagged(self.body))
        self.assertEqual(library_refs.outdated_body_objects(), [])

    def test_a_body_without_the_flag_is_outdated(self):
        self.body.property_overridable_library_set(BODY_SKETCH_PATH, False)
        self.assertEqual(library_refs.outdated_body_objects(), [self.body])

    def test_a_face_workplane_made_now_is_flagged(self):
        plane = self.face_workplane()
        self.assertTrue(plane.is_property_overridable_library(WP_SOURCE_PATH))
        self.assertEqual(library_refs.outdated_body_objects(), [])

    def test_a_face_workplane_without_the_flag_is_outdated(self):
        plane = self.face_workplane()
        plane.property_overridable_library_set(WP_SOURCE_PATH, False)
        self.assertEqual(library_refs.outdated_body_objects(), [plane])

    def test_an_overridden_old_library_is_outdated(self):
        linked, _ = self.linked_part(outdated=True)
        self.assertEqual(library_refs.outdated_libraries(), [linked.library])

    def test_a_library_saved_now_is_not_outdated(self):
        self.linked_part(outdated=False)
        self.assertEqual(library_refs.outdated_libraries(), [])

    def test_an_old_library_nobody_overrides_is_not_reported(self):
        self.linked_part(outdated=True, override=False)
        self.assertEqual(library_refs.outdated_libraries(), [])

    def test_linked_and_overridden_bodies_are_not_this_files_to_repair(self):
        self.linked_part(outdated=True)
        self.assertEqual(library_refs.outdated_body_objects(), [])


class TestRepairLibrary(OutdatedLibraryCase):
    def test_repair_flags_the_files_own_bodies(self):
        self.body.property_overridable_library_set(BODY_SKETCH_PATH, False)
        self.assertTrue(bpy.ops.view3d.slvs_repair_library.poll())
        bpy.ops.view3d.slvs_repair_library()
        self.assertTrue(flagged(self.body))
        self.assertFalse(bpy.ops.view3d.slvs_repair_library.poll())

    def test_repair_flags_the_files_own_face_workplanes(self):
        plane = self.face_workplane()
        plane.property_overridable_library_set(WP_SOURCE_PATH, False)
        bpy.ops.view3d.slvs_repair_library()
        self.assertTrue(plane.is_property_overridable_library(WP_SOURCE_PATH))

    def test_nothing_to_repair_is_not_offered(self):
        self.assertFalse(bpy.ops.view3d.slvs_repair_library.poll())

    def test_a_file_that_only_links_the_library_is_not_offered_the_repair(self):
        self.linked_part(outdated=True)
        self.assertFalse(bpy.ops.view3d.slvs_repair_library.poll())

    def test_repair_leaves_linked_and_overridden_bodies_alone(self):
        linked, override = self.linked_part(outdated=True)
        self.body.property_overridable_library_set(BODY_SKETCH_PATH, False)
        bpy.ops.view3d.slvs_repair_library()
        self.assertTrue(flagged(self.body))
        self.assertFalse(flagged(linked))
        self.assertFalse(flagged(override))
        self.assertEqual(library_refs.outdated_libraries(), [linked.library])

    def test_a_read_only_file_is_refused(self):
        self.body.property_overridable_library_set(BODY_SKETCH_PATH, False)
        with mock.patch.object(
            repair_library, "repair_blocker", return_value="This file is read-only."
        ):
            result = bpy.ops.view3d.slvs_repair_library()
        self.assertEqual(result, {"CANCELLED"})
        self.assertFalse(flagged(self.body))

    def test_the_blocker_looks_at_the_file_on_disk(self):
        with tempfile.NamedTemporaryFile(suffix=".blend") as f:
            fake_data = mock.Mock(filepath=f.name)
            with mock.patch.object(library_refs.bpy, "data", fake_data):
                with mock.patch.object(library_refs.os, "access", return_value=False):
                    self.assertTrue(library_refs.repair_blocker())
                with mock.patch.object(library_refs.os, "access", return_value=True):
                    self.assertEqual(library_refs.repair_blocker(), "")


class TestWarning(OutdatedLibraryCase):
    def test_the_warning_names_the_library_and_the_steps(self):
        linked, _ = self.linked_part(outdated=True)
        text = "\n".join(library_refs.warning_lines([linked.library]))
        self.assertIn("library.blend", text)
        self.assertIn("open the library file", text)
        self.assertIn("Repair Library File", text)
        self.assertIn("reload this file", text)

    def test_many_libraries_are_summarised(self):
        libraries = [mock.Mock(filepath=f"//lib{i}.blend") for i in range(5)]
        text = "\n".join(library_refs.warning_lines(libraries))
        self.assertIn("lib0.blend, lib1.blend, lib2.blend and 2 more", text)

    def test_the_popup_draws_the_warning(self):
        layout = mock.MagicMock()
        fake = mock.Mock(layout=layout, _lines=["one", "two"])
        outdated_library.VIEW3D_OT_slvs_outdated_library_warning.draw(fake, None)
        texts = [c.kwargs.get("text") for c in layout.label.call_args_list]
        texts += [
            c.kwargs.get("text")
            for c in layout.column.return_value.label.call_args_list
        ]
        self.assertEqual(texts[-2:], ["one", "two"])

    def test_the_popup_is_never_scheduled_in_the_background(self):
        self.assertTrue(outdated_library._in_background())
        outdated_library.schedule_warning()
        self.assertFalse(bpy.app.timers.is_registered(outdated_library._maybe_show))
        self.linked_part(outdated=True)
        with mock.patch.object(outdated_library, "_show") as op:
            self.assertIsNone(outdated_library._maybe_show())
        op.assert_not_called()

    def test_the_popup_is_shown_for_an_outdated_library(self):
        self.linked_part(outdated=True)
        with mock.patch.object(outdated_library, "_in_background", return_value=False):
            with mock.patch.object(outdated_library, "_show") as op:
                self.assertIsNone(outdated_library._maybe_show())
        op.assert_called_once_with()

    def test_no_popup_when_nothing_is_outdated(self):
        with mock.patch.object(outdated_library, "_in_background", return_value=False):
            with mock.patch.object(outdated_library, "_show") as op:
                outdated_library._maybe_show()
        op.assert_not_called()

    def _panel(self):
        layout = mock.MagicMock()
        sketch_select._draw_outdated_library_prompt(self.context, layout)
        return layout.box.return_value

    def test_the_panel_warns_without_a_repair_button_in_the_linking_file(self):
        self.linked_part(outdated=True)
        box = self._panel()
        self.assertTrue(box.alert)
        box.operator.assert_not_called()

    def test_the_panel_offers_the_repair_in_the_library_file(self):
        self.body.property_overridable_library_set(BODY_SKETCH_PATH, False)
        box = self._panel()
        self.assertEqual(box.operator.call_args.args[0], "view3d.slvs_repair_library")

    def test_the_panel_is_quiet_when_nothing_is_outdated(self):
        layout = mock.MagicMock()
        sketch_select._draw_outdated_library_prompt(self.context, layout)
        layout.box.assert_not_called()

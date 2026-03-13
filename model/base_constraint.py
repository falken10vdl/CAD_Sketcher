import logging
from typing import List

import bpy
from bpy.props import StringProperty, BoolProperty
from bpy.types import UILayout, Property, Context

from ..global_data import WpReq
from ..utilities import preferences
from ..declarations import Operators
from .constants import ENTITY_PROP_NAMES
from .base_entity import SlvsGenericEntity
from ..utilities.view import update_cb, refresh
from ..utilities.solver import update_system_cb
from ..utilities.bpy import setprop

logger = logging.getLogger(__name__)


class GenericConstraint:
    if bpy.app.version >= (5, 0):

        def _name_get_transform(self, curr_value, is_set):
            return curr_value if is_set else str(self)

        name: StringProperty(name="Name", get_transform=_name_get_transform)
    else:

        def _name_getter(self):
            return self.get("name", str(self))

        def _name_setter(self, new_name):
            self["name"] = new_name

        name: StringProperty(name="Name", get=_name_getter, set=_name_setter)
    failed: BoolProperty(name="Failed")
    visible: BoolProperty(name="Visible", default=True, update=update_cb)
    is_reference = False  # Only DimensionalConstraint can be reference
    signature = ()
    props = ()

    def needs_wp(args):
        return WpReq.OPTIONAL

    def __str__(self):
        return self.label

    def get_workplane(self):
        # NOTE: this could also check through the constraints entity workplanes
        needs_wp = self.needs_wp()

        workplane = None
        if self.sketch_i != -1:
            workplane = self.sketch.wp

        if workplane and needs_wp != WpReq.FREE:
            return workplane.py_data
        elif needs_wp == WpReq.NOT_FREE:
            return None
        else:
            import slvs

            return slvs.E_FREE_IN_3D

    def entities(self):
        props = []
        for prop_name in dir(self):
            if prop_name.endswith("_i") or not prop_name.startswith("entity"):
                continue
            entity = getattr(self, prop_name)
            if not entity:
                continue
            props.append(entity)
        return props

    def dependencies(self) -> List[SlvsGenericEntity]:
        deps = self.entities()
        if hasattr(self, "sketch"):
            s = self.sketch
            if s:
                deps.append(s)
        return deps

    # TODO: avoid duplicating code
    def update_pointers(self, index_old, index_new):
        def _update(name):
            prop = getattr(self, name)
            if prop == index_old:
                logger.debug(
                    "Update reference {} of {} to {}: ".format(name, self, index_new)
                )
                setattr(self, name, index_new)

        if hasattr(self, "sketch_i"):
            _update("sketch_i")

        for prop_name in dir(self):
            if not prop_name.startswith("entity") or not prop_name.endswith("_i"):
                continue
            _update(prop_name)

    def is_visible(self, context):
        if hasattr(self, "sketch"):
            return self.sketch.is_visible(context) and self.visible
        return self.visible

    def is_active(self, active_sketch):
        if not hasattr(self, "sketch"):
            return not active_sketch

        show_inactive = not preferences.use_experimental(
            "hide_inactive_constraints", True
        )
        if show_inactive:  # and self.is_visible(context)
            return True

        return self.sketch == active_sketch

    def draw_plane(self):
        if self.sketch_i != -1:
            wp = self.sketch.wp
            return wp.p1.location, wp.normal
        # TODO: return drawing plane for constraints in 3d
        return None, None

    def copy(self, context, entities):
        # copy itself to another set of entities
        c = context.scene.sketcher.constraints.new_from_type(self.type)
        if hasattr(self, "sketch"):
            c.sketch = self.sketch
        if hasattr(self, "setting"):
            c.setting = self.setting
        if hasattr(self, "value"):
            c.value = self.value

        for prop, e in zip(ENTITY_PROP_NAMES, entities):
            setattr(c, prop, e)

        return c

    def draw_props(self, layout: UILayout):
        is_experimental = preferences.is_experimental()

        layout.prop(self, "name", text="")

        if self.failed:
            layout.label(text="Failed", icon="ERROR")

        # Info block
        layout.separator()
        if is_experimental:
            sub = layout.column()
            sub.scale_y = 0.8
            sub.label(text="Dependencies:")
            for e in self.dependencies():
                sub.label(text=str(e))

        # General props
        layout.separator()
        layout.prop(self, "visible")

        # Specific props
        layout.separator()

        # Geometric constraints draw Delete here. Dimensional constraints draw
        # Shared Parameter + Delete directly in their own draw_props.
        if not hasattr(self, "param_name"):
            layout.separator()
            props = layout.operator(Operators.DeleteConstraint, icon="X")
            props.type = self.type
            props.index = self.index()

        return layout

    def index(self):
        """Return elements index inside its collection"""
        # HACK: Elements of collectionproperties currently don't expose an index
        # method, path_from_id writes the index however, use this hack instead
        # of looping over elements
        return int(self.path_from_id().split("[")[1].split("]")[0])

    def placements(self):
        """Return the entities where the constraint should be displayed"""
        return []

    def create_slvs_data(self, solvesys, **kwargs):
        raise NotImplementedError()

    def py_data(self, solvesys, **kwargs):
        return self.create_slvs_data(solvesys, **kwargs)


class DimensionalConstraint(GenericConstraint):

    value: Property
    setting: BoolProperty

    # ------------------------------------------------------------------
    # bexpeng integration callbacks (module-level so bpy can register them)
    # ------------------------------------------------------------------

    def _on_param_name_update(self, context: Context) -> None:
        """Re-register this constraint's parameter in bexpeng when its name changes."""
        from ..utilities.bexpeng_integration import (
            sync_constraint_to_engine,
            sync_expression_to_engine,
        )

        sync_constraint_to_engine(self)
        if (self.expression or "").strip():
            sync_expression_to_engine(self)

    def _on_expression_update(self, context: Context) -> None:
        """Register or remove the expression in bexpeng when the field changes."""
        from ..utilities.bexpeng_integration import sync_expression_to_engine

        sync_expression_to_engine(self)

    param_name: StringProperty(
        name="Parameter Name",
        description=(
            "Expose this constraint's value as a named parameter in the "
            "expression engine so other constraints can reference it "
            "(e.g. 'wall_height').  Leave empty for no engine registration."
        ),
        default="",
        update=_on_param_name_update,
    )
    expression: StringProperty(
        name="Expression",
        description=(
            "Drive this constraint's value with an expression that "
            "references other named parameters "
            "(e.g. '= 2 * wall_height').  Requires Parameter Name to be set.  "
            "Leave empty to use the value field directly."
        ),
        default="",
        update=_on_expression_update,
    )

    # ------------------------------------------------------------------
    # Value access
    # ------------------------------------------------------------------

    def _get_bexpeng_value(self):
        """Return the engine-computed displayed value if expression-driven, else None."""
        if not (self.expression or "").strip():
            return None
        param_name = (self.param_name or "").strip()
        if not param_name:
            return None
        from ..utilities.bexpeng_integration import get_engine, _ensure_subscribed

        engine = get_engine()
        if engine is None:
            return None
        # Self-heal: re-subscribe in case we missed the load_post handler.
        _ensure_subscribed(engine, param_name)
        val = engine.get_value(param_name)
        return float(val) if val is not None else None

    def _set_value(self, displayed_value: float):
        # NOTE: function signature _set_value(self, val: float, force=False)
        #       will fail when bpy tries to register the value property.
        #       See `_set_value_force()`
        if self.is_reference:
            return
        if (self.expression or "").strip():
            return  # expression-driven; ignore manual edits
        self._set_value_force(self.from_displayed_value(displayed_value))

    def _set_value_force(self, value: float):
        self.value_store = value
        from ..utilities.bexpeng_integration import push_value_to_engine

        push_value_to_engine(self)

    def _get_value(self):
        if self.is_reference:
            val = self.init_props()["value"]
            return self.to_displayed_value(val)
        bexpeng_val = self._get_bexpeng_value()
        if bexpeng_val is not None:
            return bexpeng_val
        if not self.is_property_set("value_store"):
            self.assign_init_props()
        return self.to_displayed_value(self.value_store)

    def assign_settings(self, **settings):
        for key, value in settings.items():
            if value is None:
                continue

            setprop(self, key, value)

    def assign_init_props(self, context: Context = None, **kwargs):
        self.assign_settings(**self.init_props(**kwargs))

    def on_reference_checked(self, context: Context = None):
        update_system_cb(self, context)
        self.assign_init_props()
        # Refresh the gizmos as we are changing the colors.
        refresh(context)

    is_reference: BoolProperty(
        name="Only measure",
        default=False,
        update=on_reference_checked,
    )

    def init_props(self, **kwargs):
        raise NotImplementedError()

    def to_displayed_value(self, value):
        """
        Overwrite this function to convert the property value into
        something to display on the user interface.
        NOTE: If the value is writeable, do not forget to change
              ``from_displayed_value()`` to apply the reverse operation.
        """
        return value

    def from_displayed_value(self, displayed_value):
        """
        Convert the displayed value of the property into
        a variable to store.
        NOTE: See ``to_displayed_value()``
        """
        return displayed_value

    def py_data(self, solvesys, **kwargs):
        if self.is_reference:
            return []
        return self.create_slvs_data(solvesys, **kwargs)

    def draw_props(self, layout: UILayout):
        sub = GenericConstraint.draw_props(self, layout)
        sub.prop(self, "is_reference")
        if hasattr(self, "value"):
            is_driven = bool((self.expression or "").strip())
            row = sub.row()
            row.prop(self, "value")
            row.enabled = not self.is_reference and not is_driven
        if hasattr(self, "setting"):
            sub.prop(self, "setting")

        return sub

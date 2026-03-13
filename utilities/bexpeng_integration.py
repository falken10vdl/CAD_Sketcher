# SPDX-License-Identifier: GPL-3.0-or-later
"""CAD Sketcher ↔ bexpeng integration helpers.

This module bridges CAD Sketcher's dimensional constraints with the BExpEng
parametric expression engine.  External code should only import from the
public helpers at the bottom of this file.

Constraints interact with bexpeng through two optional string properties added
to :class:`~model.base_constraint.DimensionalConstraint`:

``param_name``
    Registers this constraint's value as a **named parameter** in the engine,
    making it referenceable from other constraints' expressions.

``expression``
    A Python expression (optionally prefixed with ``=``) that **drives** this
    constraint's value, e.g. ``"= 2 * wall_height"``.  When set, the
    constraint's value is read from the engine instead of ``value_store``.

Typical workflows
-----------------
*Expose a value*::

    # Give the wall-height distance constraint the name "wall_h" in the engine.
    distance_constraint.param_name = "wall_h"

*Reference it from another constraint*::

    # Drive a second distance constraint to always equal wall_h / 2.
    distance2.param_name = "half_wall"    # name for the result (optional but useful)
    distance2.expression = "= wall_h / 2"

When ``wall_h`` changes (because the user edits the first constraint), the
engine recomputes ``half_wall`` and our subscriber callback flags the solver
dirty, triggering a re-solve.
"""

from __future__ import annotations

import logging

import bpy

logger = logging.getLogger(__name__)

# Set of param_names for which we have already registered our subscriber,
# so we never double-subscribe across the lifetime of a session.
_subscribed: set[str] = set()


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def is_bexpeng_available() -> bool:
    """Return ``True`` if the bexpeng addon can be imported."""
    try:
        import bexpeng  # noqa: F401

        return True
    except ImportError:
        return False


def get_engine():
    """Return the bexpeng singleton :class:`ParametricEngine`, or ``None``."""
    if not is_bexpeng_available():
        return None
    import bexpeng

    return bexpeng.get_engine()


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------


def _on_param_changed(param_name: str, value) -> None:
    """bexpeng subscriber: called whenever a watched parameter value changes.

    Syncs ``value_store`` for every dimensional constraint whose
    ``param_name`` matches, then flags the solver to re-run.

    This allows centrally editing a shared parameter in the BExpEng panel and
    seeing the matching CAD Sketcher dimensions update immediately, including
    value-source constraints (no local expression).
    """
    try:
        target_displayed = float(value)

        for scene in bpy.data.scenes:
            sketcher = getattr(scene, "sketcher", None)
            if sketcher is None:
                continue
            for c in sketcher.constraints.all:
                if not hasattr(c, "param_name") or c.param_name != param_name:
                    continue
                if not hasattr(c, "value_store"):
                    continue
                try:
                    # Store the engine's display-unit result back as internal value.
                    target_internal = c.from_displayed_value(target_displayed)

                    # Avoid redundant writes (and potential callback churn) when
                    # the value already matches.
                    if c.is_property_set("value_store"):
                        current_internal = c.value_store
                        if float(current_internal) == float(target_internal):
                            continue

                    c.value_store = target_internal
                except Exception:
                    pass

        from .. import global_data

        global_data.needs_solve = True
        global_data.needs_redraw = True

    except Exception as exc:
        logger.error("bexpeng subscriber error for '%s': %s", param_name, exc)


def _ensure_subscribed(engine, param_name: str) -> None:
    """Register ``_on_param_changed`` for *param_name* at most once per session."""
    if param_name in _subscribed:
        return
    engine.subscribe(param_name, _on_param_changed)
    _subscribed.add(param_name)


# ---------------------------------------------------------------------------
# Registration helpers — called by constraint property update callbacks
# ---------------------------------------------------------------------------


def sync_constraint_to_engine(constraint) -> None:
    """Register or update a constraint's parameter value in bexpeng.

    Should be called when:

    * ``param_name`` changes on a constraint.
    * The constraint's numeric value changes (via ``_set_value_force``).

    Skips expression-driven constraints — the engine drives their value, not
    the other way around.
    """
    engine = get_engine()
    if engine is None:
        return

    param_name = (getattr(constraint, "param_name", "") or "").strip()
    if not param_name:
        return

    expression = (getattr(constraint, "expression", "") or "").strip()
    if expression:
        # Expression-driven: we don't push from value_store; just ensure subscribed.
        _ensure_subscribed(engine, param_name)
        return

    # Read displayed value (what the user sees and what expressions should reference).
    if constraint.is_property_set("value_store"):
        displayed = constraint.to_displayed_value(constraint.value_store)
    else:
        displayed = 0.0

    if engine.has_parameter(param_name):
        if not engine.has_expression(param_name):
            engine.set_value(param_name, displayed)
    else:
        engine.register_parameter(param_name, displayed)

    _ensure_subscribed(engine, param_name)


def sync_expression_to_engine(constraint) -> None:
    """Register or remove a constraint's expression in bexpeng.

    Parses ``constraint.expression``:

    * Empty string → unregister any existing expression (revert to value-driven).
    * ``"= <expr>"`` or ``"<expr>"`` → register the expression.

    Does nothing if ``param_name`` is empty (expressions require a name).
    """
    engine = get_engine()
    if engine is None:
        return

    param_name = (getattr(constraint, "param_name", "") or "").strip()
    if not param_name:
        return

    expr_str = (getattr(constraint, "expression", "") or "").strip()
    # Strip the optional leading ``=`` so users can write ``"= 2 * h"`` or ``"2 * h"``.
    if expr_str.startswith("="):
        expr_str = expr_str[1:].strip()

    if not expr_str:
        engine.unregister_expression(param_name)
        return

    # Ensure the target parameter node exists in the graph.
    if not engine.has_parameter(param_name):
        engine.register_parameter(param_name, 0.0)

    try:
        engine.register_expression(param_name, expr_str)
        _ensure_subscribed(engine, param_name)
    except Exception as exc:
        logger.warning(
            "bexpeng: could not register expression '%s' for '%s': %s",
            expr_str,
            param_name,
            exc,
        )


def push_value_to_engine(constraint) -> None:
    """Push the constraint's current displayed value into bexpeng.

    Called from :meth:`~model.base_constraint.DimensionalConstraint._set_value_force`
    so that *value-source* parameters stay up-to-date whenever the user (or
    the solver) changes a constraint's value.

    Skips expression-driven constraints to avoid overwriting the engine's
    computed result.
    """
    engine = get_engine()
    if engine is None:
        return

    param_name = (getattr(constraint, "param_name", "") or "").strip()
    if not param_name:
        return

    if getattr(constraint, "expression", ""):
        return  # engine drives us; don't push back

    displayed = constraint.to_displayed_value(constraint.value_store)
    engine.set_value(param_name, displayed)
    _ensure_subscribed(engine, param_name)


# ---------------------------------------------------------------------------
# Post-load re-sync
# ---------------------------------------------------------------------------


def resync_all_constraints() -> None:
    """Rebuild engine links after load and evaluate expression-driven values.

    We do a deterministic two-pass rebuild from CAD Sketcher constraint data,
    then pull evaluated values from the engine back into ``value_store`` so
    dimensional constraints show the correct number immediately after opening
    a .blend file.
    """
    engine = get_engine()
    if engine is None:
        return

    # Stale function references from the previous Blender session are gone; reset.
    _subscribed.clear()

    constraints = []
    for scene in bpy.data.scenes:
        sketcher = getattr(scene, "sketcher", None)
        if sketcher is None:
            continue
        for c in sketcher.constraints.all:
            if not hasattr(c, "param_name"):
                continue
            param_name = (c.param_name or "").strip()
            if not param_name:
                continue
            constraints.append(c)

    # Pass 1: ensure every named constraint has a parameter node.
    for c in constraints:
        param_name = c.param_name.strip()
        if engine.has_parameter(param_name):
            continue

        if (getattr(c, "expression", "") or "").strip():
            engine.register_parameter(param_name, 0.0)
            continue

        if c.is_property_set("value_store"):
            displayed = c.to_displayed_value(c.value_store)
        else:
            displayed = 0.0
        engine.register_parameter(param_name, displayed)

    # Pass 2: register/update expressions and value-source parameters.
    for c in constraints:
        if (getattr(c, "expression", "") or "").strip():
            sync_expression_to_engine(c)
        else:
            sync_constraint_to_engine(c)

    # Pass 3: subscribe and immediately pull evaluated values for driven dims.
    for c in constraints:
        param_name = c.param_name.strip()
        _ensure_subscribed(engine, param_name)

        expr = (getattr(c, "expression", "") or "").strip()
        if not expr:
            continue

        value = engine.get_value(param_name)
        if value is None:
            continue
        try:
            c.value_store = c.from_displayed_value(float(value))
        except Exception:
            # Keep loading robust even if one constraint cannot convert.
            pass

    from .. import global_data

    global_data.needs_solve = True
    global_data.needs_redraw = True

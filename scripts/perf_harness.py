"""Headless performance harness for the interaction hot paths.

Builds sketches of increasing size and times the work that runs *per user
interaction* -- the paths behind the slowdown reported in issue #342 ("every
operation takes seconds, worse over time, fine when the sketch is hidden"):

    render_data.build   the core of both picking (per mouse-move) and the
                        overlay draw (per redraw); runs twice per frame
    solve_system        fires on every edit
    refresh_curve_geometry  rebuilds the generated mesh after a solve
    validate_all_sketches   the depsgraph self-heal pass

Run:  blender --background --python scripts/perf_harness.py
Add --profile to also cProfile render_data.build at the largest size.

This is a manual tool, not part of the CI suite -- absolute numbers are
machine-dependent; use it to compare before/after and to spot cost that scales
super-linearly with sketch size.
"""

import cProfile
import io
import pstats
import sys
import time

import addon_utils
import bpy

SIZES = (10, 25, 50, 100, 200)
PROFILE = "--profile" in sys.argv


def _enable():
    for mod in addon_utils.modules():
        if mod.__name__.split(".")[-1] == "CAD_Sketcher":
            addon_utils.enable(mod.__name__, default_set=True)
            return mod.__name__
    raise SystemExit("CAD_Sketcher not found -- is it installed?")


PKG = _enable()
M = sys.modules[PKG]
sr = M.model.sketch_ref
cr = M.model.curve_ref
cd = M.utilities.curve_data
rd = M.drawing.render_data
solve = M.curve_solver.solve_system

import importlib  # noqa: E402

validate = importlib.import_module(PKG + ".utilities.validate")


class _StubTheme:
    """Colours build() reads; values are irrelevant to timing."""

    default = selected = selected_highlight = highlight = (1, 1, 1, 1)
    fixed = inactive = inactive_selected = (1, 1, 1, 1)


def _new_sketch():
    ctx = bpy.context
    ents = ctx.scene.sketcher.entities
    ents.ensure_origin_elements(ctx)
    esk = ents.add_sketch(ents.origin_plane_XY)
    cd.ensure_sketch_curve_object(esk)
    sr.stamp_sketch_props(esk.target_object)
    return sr.Sketch(esk.target_object)


def _build_chain(sketch, n):
    """A connected chain of n distance-constrained segments (real solver work,
    real shared junctions)."""
    import math

    sc = sketch.constraints
    with cd.batch_update(sketch):
        pts = [cr.PointRef.create(sketch, (0, 0), fixed=True)]
        for i in range(1, n + 1):
            pts.append(
                cr.PointRef.create(
                    sketch, (math.cos(i) * i * 0.1, math.sin(i) * i * 0.1)
                )
            )
        lines = [cr.LineRef.create(sketch, pts[i], pts[i + 1]) for i in range(n)]
    for ln in lines:
        sc.add_distance(init=True, curve_id_1=ln.curve_id)
    return len(sketch.target_object.data.curves)


def _timeit(fn, iters):
    fn()  # warm
    t = time.perf_counter()
    for _ in range(iters):
        fn()
    return (time.perf_counter() - t) / iters * 1000  # ms/call


def main():
    ts = _StubTheme()
    header = f"{'N_seg':>6} {'curves':>7} {'build':>8} {'solve':>8} {'refresh':>8} {'validate':>9}"
    print(header + "   (ms/call)")
    last_sketch = None
    for n in SIZES:
        for o in list(bpy.data.objects):
            if o.type in ("CURVES", "EMPTY"):
                bpy.data.objects.remove(o, do_unlink=True)
        sk = _new_sketch()
        ncur = _build_chain(sk, n)
        solve(bpy.context, sketch=sk)
        scene = bpy.context.scene
        b = _timeit(lambda: rd.build(sk, ts, True), 30)
        s = _timeit(lambda: solve(bpy.context, sketch=sk), 10)
        r = _timeit(lambda: cd.refresh_curve_geometry(sk), 10)
        v = _timeit(lambda: validate.validate_all_sketches(scene), 10)
        print(f"{n:>6} {ncur:>7} {b:>8.2f} {s:>8.2f} {r:>8.2f} {v:>9.2f}")
        last_sketch = sk

    if PROFILE and last_sketch is not None:
        print(f"\n=== cProfile: render_data.build (N={SIZES[-1]}) ===")
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(50):
            rd.build(last_sketch, ts, True)
        pr.disable()
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(12)
        print("\n".join(buf.getvalue().splitlines()[:20]))


if __name__ == "__main__":
    main()

"""
Fit Selection In Frame (Rhino Python)

This script perfectly frames the active viewport camera around the
selected objects by projecting their exact 3D vertices into the
camera's 2D view space, calculating the required physical distance
based on the camera's true Field of View (FOV).

Compatible with Rhino 7 (IronPython 2.7) and Rhino 8 (Python 3).
"""

import math
import scriptcontext as sc
import rhinoscriptsyntax as rs
import Rhino

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 40.0
# ==========================================


def msg(text, icon):
    """Helper to mimic the other ports' message boxes.
    icon: 16 = error, 48 = warning."""
    rs.MessageBox(text, icon, "Fit Camera")


def margin_scale_factor():
    """Inverse Screen Percentage margin model, identical to the other ports."""
    if MARGIN_PERCENTAGE > 50.0:
        msg("WARNING: A margin greater than 50% pushes the camera very far away.\n"
            "The object may become hard to find again - use Zoom Extents if you "
            "lose it.", 48)
    occupancy = max(100.0 - MARGIN_PERCENTAGE, 0.1)
    return 100.0 / occupancy


# -------------------------------------------------------------
# COLLECT ALL WORLD-SPACE VERTICES
# -------------------------------------------------------------
def brep_meshes(obj, brep):
    """Render/display meshes for a Brep-like object: cached render meshes
    first (what you actually see), then cached display meshes, then a
    freshly generated mesh. Returns a (possibly empty) list."""
    meshes = obj.GetMeshes(Rhino.Geometry.MeshType.Render)
    if not meshes:
        meshes = obj.GetMeshes(Rhino.Geometry.MeshType.Default)
    if not meshes:
        created = Rhino.Geometry.Mesh.CreateFromBrep(
            brep, Rhino.Geometry.MeshingParameters.Default)
        meshes = list(created) if created else []
    return list(meshes)


def collect_world_points(obj, xform, points):
    """Append world-space Point3d entries for `obj` to `points`.

    Rhino stores geometry in world coordinates, so `xform` is the identity
    at the top level; it only accumulates inside block definitions (where
    geometry lives in definition space). Fallback ladder per object:
    exact mesh vertices -> render/display/generated meshes -> curve control
    polygon (guaranteed to contain the curve) -> point location ->
    accurate bounding-box corners -> silent skip.
    """
    # Block instance: recurse into the definition with the accumulated
    # transform (handles nested blocks).
    if isinstance(obj, Rhino.DocObjects.InstanceObject):
        idef = obj.InstanceDefinition
        if idef is None:
            return
        child_xform = xform * obj.InstanceXform
        for child in idef.GetObjects():
            collect_world_points(child, child_xform, points)
        return

    geo = obj.Geometry
    if geo is None:
        return

    try:
        if isinstance(geo, Rhino.Geometry.Mesh):
            for v in geo.Vertices:
                points.append(xform * Rhino.Geometry.Point3d(v))
            return

        brep = None
        if isinstance(geo, Rhino.Geometry.Brep):
            brep = geo
        elif isinstance(geo, Rhino.Geometry.Extrusion):
            brep = geo.ToBrep()
        elif isinstance(geo, Rhino.Geometry.Surface):
            brep = Rhino.Geometry.Brep.CreateFromSurface(geo)

        if brep is not None:
            meshes = brep_meshes(obj, brep)
            if meshes:
                for mesh in meshes:
                    for v in mesh.Vertices:
                        points.append(xform * Rhino.Geometry.Point3d(v))
                return
            # fall through to the bounding-box fallback below

        elif isinstance(geo, Rhino.Geometry.Curve):
            nc = geo.ToNurbsCurve()
            if nc is not None:
                # The NURBS control polygon is mathematically guaranteed to
                # contain the curve - errs slightly on the safe side.
                for i in range(nc.Points.Count):
                    points.append(xform * nc.Points[i].Location)
                return

        elif isinstance(geo, Rhino.Geometry.Point):
            points.append(xform * geo.Location)
            return
    except Exception:
        pass  # fall through to the bounding-box fallback

    # FALLBACK: lights, annotations, dimensions, hatches, SubD, failures.
    try:
        bbox = geo.GetBoundingBox(True)
        if bbox.IsValid:
            for corner in bbox.GetCorners():
                points.append(xform * corner)
    except Exception:
        pass  # no usable bounds - skip the object silently


def fit_selection_in_frame():
    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # -------------------------------------------------------------
    view = sc.doc.Views.ActiveView
    if view is None:
        msg("No active view found.", 16)
        return
    vp = view.ActiveViewport
    # (A Rhino viewport always has a camera, so no camera check is needed.)

    objs = list(sc.doc.Objects.GetSelectedObjects(True, False))
    if not objs:
        msg("Please select at least one object to fit into the camera view.", 16)
        return

    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    all_verts_world = []
    identity = Rhino.Geometry.Transform.Identity
    for obj in objs:
        collect_world_points(obj, identity, all_verts_world)

    if not all_verts_world:
        msg("No valid geometry points found to fit.", 16)
        return

    # -------------------------------------------------------------
    # 3. PROJECT WORLD VERTICES INTO CAMERA-LOCAL SPACE
    # -------------------------------------------------------------
    # CameraX/Y/Z are the camera's unit right/up/backward vectors (Rhino
    # cameras look down -Z), so vertices in front of the lens get NEGATIVE
    # local Z - the same convention as all other ports, keeping the fitting
    # core identical.
    right = vp.CameraX
    up = vp.CameraY
    backward = vp.CameraZ
    campos = vp.CameraLocation

    local_verts = []
    for p in all_verts_world:
        d = p - campos
        local_verts.append((d * right, d * up, d * backward))  # * = dot

    if vp.IsParallelProjection:
        fit_parallel(view, vp, campos, right, up, backward, local_verts)
    else:
        # Perspective and two-point perspective. GetCameraAngle returns
        # half-angles already adjusted for the viewport's aspect ratio.
        rc = vp.GetCameraAngle()
        ok = rc[0]
        half_vert = rc[2]
        half_horiz = rc[3]
        tan_h = math.tan(half_horiz)
        tan_v = math.tan(half_vert)
        if not ok or tan_h <= 0.0 or tan_v <= 0.0:
            msg("Could not read the camera's field of view.", 16)
            return
        fit_perspective(view, vp, campos, right, up, backward,
                        local_verts, tan_h, tan_v)


# -------------------------------------------------------------
# ITERATIVE SCREEN-SPACE CENTERING AND SCALING (perspective)
# -------------------------------------------------------------
def fit_perspective(view, vp, campos, right, up, backward, local_verts,
                    tan_h, tan_v):
    scale_factor = margin_scale_factor()

    xs = [v[0] for v in local_verts]
    ys = [v[1] for v in local_verts]
    zs = [v[2] for v in local_verts]

    current_offset_x = (min(xs) + max(xs)) / 2.0
    current_offset_y = (min(ys) + max(ys)) / 2.0
    center_z = (min(zs) + max(zs)) / 2.0

    best_offset_z = -float('inf')

    # Iterate up to 10 times to balance the X/Y optical center with the Z depth.
    for _ in range(10):
        max_required_offset_z = -float('inf')

        for x, y, z in local_verts:
            dx = abs(x - current_offset_x) * scale_factor
            dy = abs(y - current_offset_y) * scale_factor

            min_depth_h = dx / tan_h if dx > 0.0001 else 0.0
            min_depth_v = dy / tan_v if dy > 0.0001 else 0.0

            required_offset_z = z + max(min_depth_h, min_depth_v)
            if required_offset_z > max_required_offset_z:
                max_required_offset_z = required_offset_z

        # Failsafe for zero-volume selections.
        if math.isinf(max_required_offset_z) or math.isnan(max_required_offset_z):
            max_required_offset_z = max(zs) + 10.0

        best_offset_z = max_required_offset_z

        screenspace_xs = []
        screenspace_ys = []

        for x, y, z in local_verts:
            depth = best_offset_z - z
            if depth < 0.0001:
                depth = 0.0001
            screenspace_xs.append((x - current_offset_x) / (depth * tan_h))
            screenspace_ys.append((y - current_offset_y) / (depth * tan_v))

        optical_center_x = (min(screenspace_xs) + max(screenspace_xs)) / 2.0
        optical_center_y = (min(screenspace_ys) + max(screenspace_ys)) / 2.0

        physical_shift_x = optical_center_x * (best_offset_z - center_z) * tan_h
        physical_shift_y = optical_center_y * (best_offset_z - center_z) * tan_v

        current_offset_x += physical_shift_x
        current_offset_y += physical_shift_y

        if abs(physical_shift_x) < 0.001 and abs(physical_shift_y) < 0.001:
            break

    # -------------------------------------------------------------
    # APPLY THE NEW CAMERA
    # -------------------------------------------------------------
    new_location = (campos + right * current_offset_x
                    + up * current_offset_y + backward * best_offset_z)

    # The camera target is first-class in Rhino (like Max): put it on the
    # new optical axis at the selection's depth center so later orbits
    # pivot around the framed object.
    new_targ_dist = best_offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0
    forward = -backward
    new_target = new_location + forward * new_targ_dist

    # Note the argument order: target first, then camera location.
    vp.SetCameraLocations(new_target, new_location)
    view.Redraw()


# -------------------------------------------------------------
# PARALLEL PROJECTION FIT
# -------------------------------------------------------------
# No iteration needed: parallel projection has no perspective distortion,
# so the geometric center IS the optical center. Fitting means recentering
# the camera and setting the view rectangle (frustum), not moving back.
def fit_parallel(view, vp, campos, right, up, backward, local_verts):
    scale_factor = margin_scale_factor()

    xs = [v[0] for v in local_verts]
    ys = [v[1] for v in local_verts]
    zs = [v[2] for v in local_verts]

    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    center_z = (min(zs) + max(zs)) / 2.0

    # Distance does not affect framing in parallel projection, but geometry
    # behind the eye can clip - if any vertex is behind (local z > 0), slide
    # the eye back until everything is in front, with 10% depth padding.
    offset_z = 0.0
    if max(zs) > 0.0:
        padding = max((max(zs) - min(zs)) * 0.1, 1.0)
        offset_z = max(zs) + padding

    new_location = (campos + right * center_x + up * center_y
                    + backward * offset_z)

    new_targ_dist = offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0
    forward = -backward
    new_target = new_location + forward * new_targ_dist

    # Recenter first (target first, then camera location), THEN snapshot
    # the viewport for the frustum change so the snapshot carries the new
    # camera.
    vp.SetCameraLocations(new_target, new_location)

    rc = vp.GetFrustum()
    ok = rc[0]
    if not ok:
        view.Redraw()
        msg("Could not read the viewport frustum.", 16)
        return
    f_left, f_right, f_bottom, f_top, f_near, f_far = rc[1], rc[2], rc[3], rc[4], rc[5], rc[6]

    # For a parallel projection the frustum IS the view rectangle in world
    # units. Keep its aspect, set its size from the extents + margin.
    aspect = (f_right - f_left) / (f_top - f_bottom)
    extent_x = max(xs) - min(xs)
    extent_y = max(ys) - min(ys)
    half_w = max(extent_x, extent_y * aspect) * scale_factor / 2.0
    if half_w < 0.001:
        half_w = 0.001
    half_h = half_w / aspect

    vpinfo = Rhino.DocObjects.ViewportInfo(vp)
    vpinfo.SetFrustum(-half_w, half_w, -half_h, half_h, f_near, f_far)
    vp.SetViewProjection(vpinfo, True)
    view.Redraw()


# Direct call (matches the Houdini port): works from EditPythonScript,
# the Rhino 8 ScriptEditor, and _-RunPythonScript alike.
fit_selection_in_frame()

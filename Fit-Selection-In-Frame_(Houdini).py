"""
Fit Selection In Frame (Houdini Python)

This script perfectly frames the active camera around the selected
objects by projecting their exact 3D vertices into the camera's
2D view space, calculating the required physical distance
based on the camera's true Field of View (FOV).
"""

import math
import hou

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 15.0
# ==========================================


def msg(text, severity=None):
    """Helper to mimic the other ports' message boxes."""
    if severity is None:
        severity = hou.severityType.Error
    hou.ui.displayMessage(text, severity=severity, title="Fit Camera")


def margin_scale_factor():
    """Inverse Screen Percentage margin model, identical to the other ports."""
    if MARGIN_PERCENTAGE > 50.0:
        msg("WARNING: A margin greater than 50% pushes the camera very far away.\n"
            "You may need to increase the camera's Far Clipping ('far' parameter) "
            "so the object stays visible.",
            severity=hou.severityType.Warning)
    occupancy = max(100.0 - MARGIN_PERCENTAGE, 0.1)
    return 100.0 / occupancy


# -------------------------------------------------------------
# COLLECT ALL WORLD-SPACE VERTICES
# -------------------------------------------------------------
def collect_world_points(node, points):
    """Append world-space hou.Vector3 points for `node` to `points`.

    OBJ geometry nodes contribute their display SOP's points (what you see
    is what you frame, all procedural networks cooked). SOP nodes selected
    inside a geo network contribute their own geometry. Everything else that
    is an OBJ (lights, nulls, bones, cook failures, zero-point geometry)
    falls back to its world-space origin as a single point - Houdini
    non-geometry objects have no meaningful bounding box. Nodes that are
    neither OBJ nor SOP (LOP/DOP/COP/ROP...) have no world transform and
    are skipped entirely.
    """
    if isinstance(node, hou.ObjNode):
        sop = node.displayNode()
        xform = node.worldTransform()
    elif isinstance(node, hou.SopNode):
        sop = node
        parent = node.parent()
        while parent is not None and not isinstance(parent, hou.ObjNode):
            parent = parent.parent()
        if parent is None:
            return
        xform = parent.worldTransform()
    else:
        return

    if sop is not None:
        try:
            geo = sop.geometry()
            if geo is not None:
                raw = geo.pointFloatAttribValues("P")
                if raw:
                    for i in range(0, len(raw), 3):
                        p = hou.Vector3(raw[i], raw[i + 1], raw[i + 2])
                        points.append(p * xform)
                    return
        except Exception:
            pass  # Cook error - fall through to the origin fallback.

    # FALLBACK: single point at the node's world-space origin.
    points.append(xform.extractTranslates())


def fit_selection_in_frame():
    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # -------------------------------------------------------------
    sv = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if sv is None:
        msg("No Scene Viewer pane found.")
        return

    cam = sv.curViewport().camera()
    if cam is None:
        msg("The viewport is not looking through a camera.\n"
            "Lock the view to a camera first.")
        return

    sel = hou.selectedNodes()
    if not sel:
        msg("Please select at least one object to fit into the camera view.")
        return

    if (cam.parm("focal") is None or cam.parm("aperture") is None
            or cam.parmTuple("res") is None):
        msg("The active camera is not a standard Houdini camera.")
        return

    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    all_verts_world = []
    for node in sel:
        if node == cam:
            continue  # never fit the camera to itself
        collect_world_points(node, all_verts_world)

    if not all_verts_world:
        msg("No valid geometry points found to fit.")
        return

    # -------------------------------------------------------------
    # 3. PROJECT WORLD VERTICES INTO CAMERA-LOCAL SPACE
    # -------------------------------------------------------------
    # worldTransform() rows are the camera's local axes (row-major). Houdini
    # cameras look down -Z, so row 2 IS the backward vector and vertices in
    # front of the lens get NEGATIVE local Z - the same convention as the
    # other ports, keeping the fitting core identical. Rows are normalized
    # to be robust against a (meaningless) scaled camera transform.
    m = cam.worldTransform()
    right = hou.Vector3(m.at(0, 0), m.at(0, 1), m.at(0, 2)).normalized()
    up = hou.Vector3(m.at(1, 0), m.at(1, 1), m.at(1, 2)).normalized()
    backward = hou.Vector3(m.at(2, 0), m.at(2, 1), m.at(2, 2)).normalized()
    campos = m.extractTranslates()

    local_verts = []
    for p in all_verts_world:
        d = p - campos
        local_verts.append((d.dot(right), d.dot(up), d.dot(backward)))

    # -------------------------------------------------------------
    # 4. DETERMINE THE CAMERA FRUSTUM
    # -------------------------------------------------------------
    resx, resy = cam.parmTuple("res").eval()
    if resx <= 0 or resy <= 0:
        msg("Camera has an invalid render resolution.")
        return
    aspect_parm = cam.parm("aspect")
    pixel_aspect = aspect_parm.eval() if aspect_parm is not None else 1.0

    projection_parm = cam.parm("projection")
    projection = projection_parm.eval() if projection_parm is not None else 0

    if projection == 0:
        # Houdini's camera model is focal length + film aperture. The
        # vertical aperture follows from the render resolution and pixel
        # aspect ratio ("aspect ratio safe", like the Max/Maya ports).
        focal = cam.evalParm("focal")
        aperture = cam.evalParm("aperture")
        if focal <= 0.0 or aperture <= 0.0:
            msg("Camera has no usable focal length / aperture.")
            return
        tan_h = (aperture / 2.0) / focal
        tan_v = tan_h * (resy * pixel_aspect) / resx
        fit_perspective(cam, campos, right, up, backward,
                        local_verts, tan_h, tan_v)
    elif projection == 1:
        fit_orthographic(cam, campos, right, up, backward,
                         local_verts, resx, resy, pixel_aspect)
    else:
        msg("Only Perspective and Orthographic camera projections "
            "are supported.")
        return


# -------------------------------------------------------------
# 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING (perspective)
# -------------------------------------------------------------
def fit_perspective(cam, campos, right, up, backward, local_verts,
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
    # 6. APPLY THE NEW CAMERA
    # -------------------------------------------------------------
    new_pos = (campos + right * current_offset_x + up * current_offset_y
               + backward * best_offset_z)

    new_targ_dist = best_offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0

    apply_camera(cam, new_pos, new_targ_dist)


def apply_camera(cam, new_pos, focus_distance, orthowidth=None):
    """Move the camera to new_pos keeping its orientation, update the focus
    distance (and ortho width if given), all inside a single undo group so
    one Ctrl+Z restores everything. setWorldTransform computes the correct
    local parm values even for parented cameras."""
    with hou.undos.group("Fit Selection In Frame"):
        m = cam.worldTransform()
        rows = [list(r) for r in m.asTupleOfTuples()]
        rows[3] = [new_pos[0], new_pos[1], new_pos[2], 1.0]
        cam.setWorldTransform(hou.Matrix4(rows))

        if orthowidth is not None:
            ow_parm = cam.parm("orthowidth")
            if ow_parm is not None:
                ow_parm.set(orthowidth)

        # Focus distance is Houdini's equivalent of the other ports' target
        # distance (mirrors the Blender port's dof.focus_distance).
        focus_parm = cam.parm("focus")
        if focus_parm is not None:
            focus_parm.set(focus_distance)


# -------------------------------------------------------------
# ORTHOGRAPHIC PROJECTION FIT
# -------------------------------------------------------------
# No iteration needed: orthographic projection has no perspective
# distortion, so the geometric center IS the optical center. Fitting means
# centering the camera in the view plane and setting the ortho width, not
# moving the camera back.
def fit_orthographic(cam, campos, right, up, backward, local_verts,
                     resx, resy, pixel_aspect):
    scale_factor = margin_scale_factor()

    xs = [v[0] for v in local_verts]
    ys = [v[1] for v in local_verts]
    zs = [v[2] for v in local_verts]

    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    center_z = (min(zs) + max(zs)) / 2.0

    # Distance does not affect framing in orthographic projection, but
    # geometry behind the eye can clip - if any vertex is behind (local
    # z > 0), slide the eye back until everything is in front, with 10%
    # depth padding.
    offset_z = 0.0
    if max(zs) > 0.0:
        padding = max((max(zs) - min(zs)) * 0.1, 1.0)
        offset_z = max(zs) + padding

    # orthowidth is the view's horizontal width; the frame's width/height
    # ratio follows from the render resolution and pixel aspect.
    frame_aspect = resx / (resy * pixel_aspect)
    extent_x = max(xs) - min(xs)
    extent_y = max(ys) - min(ys)
    orthowidth = max(extent_x, extent_y * frame_aspect) * scale_factor
    if orthowidth < 0.001:
        orthowidth = 0.001

    new_pos = campos + right * center_x + up * center_y + backward * offset_z

    new_targ_dist = offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0

    apply_camera(cam, new_pos, new_targ_dist, orthowidth=orthowidth)


# NOTE: No `if __name__ == "__main__"` guard - Houdini's Python Source
# Editor executes this file inside the hou.session module and Shelf Tools
# run it in their own namespace, so the guard would never fire in either.
fit_selection_in_frame()

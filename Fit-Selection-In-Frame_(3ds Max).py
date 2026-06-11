"""
Fit Selection In Frame (3ds Max Python)

This script perfectly frames the active camera around the selected 
objects by projecting their exact 3D vertices into the camera's 
2D view space, calculating the required physical distance 
based on the camera's true Field of View (FOV).
""" 

import pymxs
import math

rt = pymxs.runtime

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 15
# ==========================================

def fit_selection_in_frame():
    
    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # Ensure a camera is active and objects are selected
    # -------------------------------------------------------------
    cam = rt.viewport.getCamera()
    if not cam:
        rt.messageBox("No camera found in active viewport.\nPlease activate a Camera viewport before running this tool.", title="Fit Camera", beep=True)
        return
        
    sel = rt.selection
    if len(sel) == 0:
        rt.messageBox("Please select at least one object to fit into the camera view.", title="Fit Camera", beep=True)
        return
        
    all_verts_world = []
    
    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    for obj in sel:
        # We must ignore the camera itself or its target if the user accidentally selected them. 
        # Attempting to fit the camera to its own geometry will cause infinite math loops.
        is_cam = (obj == cam)
        if rt.isProperty(cam, "target") and obj == getattr(cam, "target", None):
            is_cam = True
            
        if is_cam: 
            continue
            
        try:
            # snapshotAsMesh is the safest way to get the final evaluated geometry of an object 
            # in 3ds Max (e.g. after modifiers are applied). It returns a temporary TriMesh in memory.
            mesh = rt.snapshotAsMesh(obj)
            num_verts = rt.getNumVerts(mesh)
            
            # MaxScript arrays and indices are 1-based, so we iterate from 1 to num_verts + 1.
            for i in range(1, num_verts + 1):
                all_verts_world.append(rt.getVert(mesh, i))
                
            rt.delete(mesh) # Extremely important: Delete the temporary TriMesh to prevent memory leaks

        except Exception:
            # FALLBACK: If the object isn't geometry (e.g. a Light, Helper, or Spline), it won't 
            # have a mesh. In this case, we just grab its world-space bounding box corners instead.
            omin, omax = obj.min, obj.max
            corners = [
                rt.Point3(omin.x, omin.y, omin.z), rt.Point3(omax.x, omin.y, omin.z),
                rt.Point3(omin.x, omax.y, omin.z), rt.Point3(omax.x, omax.y, omin.z),
                rt.Point3(omin.x, omin.y, omax.z), rt.Point3(omax.x, omin.y, omax.z),
                rt.Point3(omin.x, omax.y, omax.z), rt.Point3(omax.x, omax.y, omax.z)
            ]
            all_verts_world.extend(corners)
            
    # If the script fails to find any usable points (like selecting an empty group)
    if not all_verts_world:
        rt.messageBox("No valid geometry points found to fit.", title="Fit Camera", beep=True)
        return

    # -------------------------------------------------------------
    # 3. UNDERSTANDING 3DS MAX CAMERA SPACE
    # -------------------------------------------------------------
    # To do mathematics on how the camera "sees" the vertices, we must convert 
    # their World Coordinates (X, Y, Z based on the grid origin) into 
    # Local Camera Coordinates (where X/Y/Z are relative to the lens).
    #
    # In 3ds Max:
    #   Local X axis = Right (from the camera's perspective)
    #   Local Y axis = Up (from the camera's perspective)
    #   Local Z axis = Backward (The camera physically looks down its NEGATIVE Z axis)
    
    # We get the camera's world transform matrix and invert it to bring points into its local space
    tm = cam.transform
    invTm = rt.inverse(tm)
    
    # Project all world vertices into the camera's local space coordinates
    local_verts = [v * invTm for v in all_verts_world]
    
    # -------------------------------------------------------------
    # 4. DETERMINE CAMERA FIELD OF VIEW (FOV)
    # -------------------------------------------------------------
    # FOV is how wide the camera's view cone is, measured in degrees.
    hFov = 45.0
    if rt.isProperty(cam, "fov"):
        hFov = cam.fov
    else:
        # Fallback if no FOV (e.g. orthographic or a custom plugin physical camera)
        rt.messageBox("Camera does not have a standard FOV property accessible. Assuming 45 degrees.", title="Fit Camera", beep=False)

    # In 3ds Max, the generic FOV property is purely the HORIZONTAL angle of the view frustum.
    # To mathematically fit vertices into this frustum, we need the slope of its walls.
    # We find this by taking the tangent of *half* the FOV angle.
    tan_h = math.tan(math.radians(hFov / 2.0))
    
    # To find the VERTICAL slope of the frustum walls, we divide by the Aspect Ratio.
    # We explicitly use the Render Aspect Ratio because that represents the final encoded image.
    render_aspect = float(rt.renderWidth) / float(rt.renderHeight)
    tan_v = tan_h / render_aspect

    # -------------------------------------------------------------
    # 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING
    # -------------------------------------------------------------
    # Because a camera uses Perspective Projection, objects closer to the lens
    # appear larger and shift outward faster than objects further away.
    # We cannot simply find the 3D center of the object (offset_x, offset_y) because 
    # the 2D visual center changes depending on how far the camera pulls back (offset_z).
    # 
    # Solution: We iteratively test the projection multiple times until we find the exact 
    # physical X, Y, and Z required to balance A1=A2 and B1=B2 optically.

    # Initial guess: Camera starts at the flat 3D center of the object.
    current_offset_x = (min(v.x for v in local_verts) + max(v.x for v in local_verts)) / 2.0
    current_offset_y = (min(v.y for v in local_verts) + max(v.y for v in local_verts)) / 2.0
    
    # center_z is the middle of the object depth-wise (-100 could be back of object, -50 front)
    center_z = (min(v.z for v in local_verts) + max(v.z for v in local_verts)) / 2.0
    
    # Inverse Screen Percentage calculation:
    # If Margin = 0%, the object touches the edge of the frame.
    # If Margin = 50%, the object covers exactly 50% of the middle of the frame.
    # If Margin = 99%, the object takes up only 1% of the frame (pushed extremely far away).

    if MARGIN_PERCENTAGE > 50.0:
        rt.messageBox("WARNING: A margin greater than 50% means the camera will be pushed extremely far away to squeeze the object into less than half the screen.\n\nYou may need to increase the Camera's physical 'Far Clipping Plane' limit, otherwise the object might disappear from the render!", title="High Margin Warning", beep=True)
        
    occupancy = 100.0 - MARGIN_PERCENTAGE
    if occupancy < 0.1:
        occupancy = 0.1
        
    scale_factor = 100.0 / occupancy
    
    best_offset_z = -float('inf')
    
    # Iterate up to 10 times to let the X/Y optical center balance with the Z depth.
    # Usually it stabilizes perfectly within 3-4 iterations.
    for iteration in range(10):
        
        max_required_offset_z = -float('inf')
        
        # Calculate the required Z depth based on our current X/Y camera center
        for v in local_verts:
            # We apply the scale factor directly to this required virtual distance.
            dx = abs(v.x - current_offset_x) * scale_factor
            dy = abs(v.y - current_offset_y) * scale_factor
            
            min_depth_h = (dx / tan_h) if dx > 0.0001 else 0.0
            min_depth_v = (dy / tan_v) if dy > 0.0001 else 0.0
            
            required_d = max(min_depth_h, min_depth_v)
            required_offset_z = v.z + required_d
            
            if required_offset_z > max_required_offset_z:
                max_required_offset_z = required_offset_z
                
        # Failsafe for zero-volume selections
        if math.isinf(max_required_offset_z) or math.isnan(max_required_offset_z):
            max_required_offset_z = max(v.z for v in local_verts) + 10.0
            
        best_offset_z = max_required_offset_z
        
        # Now, knowing the camera is pulled back to `best_offset_z`, we calculate where
        # every vertex *actually appears* in the 2D optical screen space (from -1.0 to 1.0).
        screenspace_xs = []
        screenspace_ys = []
        
        for v in local_verts:
            # Physical distance from lens to vertex
            depth = best_offset_z - v.z
            if depth < 0.0001: depth = 0.0001
            
            # Optical projection (divide physical X/Y by View depth and frustum slope)
            # This turns physical coordinates into standard screen coordinates
            sx = (v.x - current_offset_x) / (depth * tan_h)
            sy = (v.y - current_offset_y) / (depth * tan_v)
            
            screenspace_xs.append(sx)
            screenspace_ys.append(sy)
            
        # Find the optical bounding box of the object on-screen
        min_sx, max_sx = min(screenspace_xs), max(screenspace_xs)
        min_sy, max_sy = min(screenspace_ys), max(screenspace_ys)
        
        # Calculate the optical error (how far off-center it looks on screen)
        # We want the optical center to be exactly 0.0
        optical_center_x = (min_sx + max_sx) / 2.0
        optical_center_y = (min_sy + max_sy) / 2.0
        
        # We translate this optical error back into a physical shift for the next iteration.
        # Average depth of the bounding vertices determines how much physical shift is needed.
        physical_shift_x = optical_center_x * (best_offset_z - center_z) * tan_h
        physical_shift_y = optical_center_y * (best_offset_z - center_z) * tan_v
        
        current_offset_x += physical_shift_x
        current_offset_y += physical_shift_y
        
        # If the shift is microscopic, we have reached mathematical perfection! Break early.
        if abs(physical_shift_x) < 0.001 and abs(physical_shift_y) < 0.001:
            break

    # -------------------------------------------------------------
    # 6. APPLY NEW TRANSFORMATIONS SEAMLESSLY
    # -------------------------------------------------------------
    with pymxs.undo(True, "Fit Camera Screen Space"):
        orig_pos = cam.pos
        
        # Move camera by current_offset_x, current_offset_y, and best_offset_z along local axes.
        cam.pos = orig_pos + tm.row1 * current_offset_x + tm.row2 * current_offset_y + tm.row3 * best_offset_z
        
        # Re-target calculation
        new_targ_dist = best_offset_z - center_z
        if new_targ_dist < 0.1: new_targ_dist = 10.0
        
        if rt.isProperty(cam, "target") and getattr(cam, "target", None) is not None:
            # Target should sit directly on our new optical camera center axis at the depth center
            cam.target.pos = orig_pos + tm.row1 * current_offset_x + tm.row2 * current_offset_y + tm.row3 * center_z
            
        if rt.isProperty(cam, "targDist"):
            cam.targDist = new_targ_dist
        if rt.isProperty(cam, "target_distance"):
            cam.target_distance = new_targ_dist

if __name__ == "__main__":
    fit_selection_in_frame()

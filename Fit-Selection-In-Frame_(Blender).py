"""
Fit Selection In Frame (Blender Python)

This script perfectly frames the active camera around the selected 
objects by projecting their exact 3D vertices into the camera's 
2D view space, calculating the required physical distance 
based on the camera's true Field of View (FOV).
"""

import bpy
import math
from mathutils import Vector

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 15.0
# ==========================================

def ShowMessageBox(message="", title="Message Box", icon='INFO'):
    """Helper to mimic 3ds Max's rt.messageBox."""
    def draw(self, context):
        # Split message by newlines to show properly in Blender's UI
        for line in message.split("\n"):
            self.layout.label(text=line)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

def fit_selection_in_frame():
    context = bpy.context
    scene = context.scene

    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # -------------------------------------------------------------
    cam = scene.camera
    if not cam:
        ShowMessageBox("No camera found in the active scene.\nPlease set an active Scene Camera.", title="Fit Camera", icon='ERROR')
        return
        
    sel = context.selected_objects
    if not sel:
        ShowMessageBox("Please select at least one object to fit into the camera view.", title="Fit Camera", icon='ERROR')
        return
        
    all_verts_world = []
    
    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    # Get the dependency graph to evaluate modifiers
    depsgraph = context.evaluated_depsgraph_get()
    
    for obj in sel:
        if obj == cam: 
            continue
            
        # Try to get evaluated mesh data
        if obj.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}:
            eval_obj = obj.evaluated_get(depsgraph)
            try:
                mesh = eval_obj.to_mesh()
                if mesh:
                    matrix = eval_obj.matrix_world
                    # Append transformed world-coordinate vertices
                    all_verts_world.extend([matrix @ v.co for v in mesh.vertices])
                    eval_obj.to_mesh_clear() # Prevent memory leaks
            except Exception as e:
                print(f"Could not get mesh for {obj.name}: {e}")
        else:
            # FALLBACK: Lights, Empties, etc. Use bounding box corners.
            matrix = obj.matrix_world
            all_verts_world.extend([matrix @ Vector(corner) for corner in obj.bound_box])
            
    if not all_verts_world:
        ShowMessageBox("No valid geometry points found to fit.", title="Fit Camera", icon='ERROR')
        return

    # -------------------------------------------------------------
    # 3. UNDERSTANDING BLENDER CAMERA SPACE
    # -------------------------------------------------------------
    # Get the camera's world transform matrix and invert it to bring points into local space
    cam_matrix_inv = cam.matrix_world.inverted()
    local_verts = [cam_matrix_inv @ v for v in all_verts_world]
    
    # -------------------------------------------------------------
    # 4. DETERMINE CAMERA FIELD OF VIEW (FOV)
    # -------------------------------------------------------------
    # Blender's view_frame() returns the 4 corners of the camera frustum at a specific depth.
    # This automatically accounts for Aspect Ratio, Sensor Size, and FOV!
    frame = cam.data.view_frame(scene=scene)
    top_right = frame[0] # Top-right corner vector
    
    # Normalize the X and Y bounds by the Z depth to get the slope tangents
    depth_z = abs(top_right.z)
    tan_h = abs(top_right.x) / depth_z
    tan_v = abs(top_right.y) / depth_z

    # -------------------------------------------------------------
    # 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING
    # -------------------------------------------------------------
    current_offset_x = (min(v.x for v in local_verts) + max(v.x for v in local_verts)) / 2.0
    current_offset_y = (min(v.y for v in local_verts) + max(v.y for v in local_verts)) / 2.0
    center_z = (min(v.z for v in local_verts) + max(v.z for v in local_verts)) / 2.0
    
    if MARGIN_PERCENTAGE > 50.0:
        ShowMessageBox("WARNING: A margin greater than 50% means the camera will be pushed extremely far away.\nCheck your Far Clipping Plane limit!", title="High Margin Warning", icon='ERROR')
        
    occupancy = max(100.0 - MARGIN_PERCENTAGE, 0.1)
    scale_factor = 100.0 / occupancy
    
    best_offset_z = -float('inf')
    
    # Iterate to let the X/Y optical center balance with the Z depth.
    for iteration in range(10):
        max_required_offset_z = -float('inf')
        
        # Calculate required Z depth
        for v in local_verts:
            dx = abs(v.x - current_offset_x) * scale_factor
            dy = abs(v.y - current_offset_y) * scale_factor
            
            min_depth_h = (dx / tan_h) if dx > 0.0001 else 0.0
            min_depth_v = (dy / tan_v) if dy > 0.0001 else 0.0
            
            required_d = max(min_depth_h, min_depth_v)
            required_offset_z = v.z + required_d
            
            if required_offset_z > max_required_offset_z:
                max_required_offset_z = required_offset_z
                
        # Failsafe
        if math.isinf(max_required_offset_z) or math.isnan(max_required_offset_z):
            max_required_offset_z = max(v.z for v in local_verts) + 10.0
            
        best_offset_z = max_required_offset_z
        
        screenspace_xs = []
        screenspace_ys = []
        
        # Calculate optical projection
        for v in local_verts:
            depth = best_offset_z - v.z
            if depth < 0.0001: depth = 0.0001
            
            sx = (v.x - current_offset_x) / (depth * tan_h)
            sy = (v.y - current_offset_y) / (depth * tan_v)
            
            screenspace_xs.append(sx)
            screenspace_ys.append(sy)
            
        min_sx, max_sx = min(screenspace_xs), max(screenspace_xs)
        min_sy, max_sy = min(screenspace_ys), max(screenspace_ys)
        
        optical_center_x = (min_sx + max_sx) / 2.0
        optical_center_y = (min_sy + max_sy) / 2.0
        
        physical_shift_x = optical_center_x * (best_offset_z - center_z) * tan_h
        physical_shift_y = optical_center_y * (best_offset_z - center_z) * tan_v
        
        current_offset_x += physical_shift_x
        current_offset_y += physical_shift_y
        
        if abs(physical_shift_x) < 0.001 and abs(physical_shift_y) < 0.001:
            break

    # -------------------------------------------------------------
    # 6. APPLY NEW TRANSFORMATIONS SEAMLESSLY
    # -------------------------------------------------------------
    # Capture the original location and the local directional axes
    orig_pos = cam.matrix_world.translation.copy()
    cam_x = cam.matrix_world.col[0].xyz # Local Right
    cam_y = cam.matrix_world.col[1].xyz # Local Up
    cam_z = cam.matrix_world.col[2].xyz # Local Backward

    # Move camera along its local axes
    cam.location = orig_pos + (cam_x * current_offset_x) + (cam_y * current_offset_y) + (cam_z * best_offset_z)
    
    # Update Focus Distance (Blender's equivalent of Target Distance)
    new_targ_dist = best_offset_z - center_z
    if new_targ_dist < 0.1: new_targ_dist = 10.0
    cam.data.dof.focus_distance = new_targ_dist

if __name__ == "__main__":
    fit_selection_in_frame()
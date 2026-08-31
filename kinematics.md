# ASSIGNMENT — Mecanum Car Kinematics
**Project:** ENRO / Mecanum Car  
**Assigned to:** Hasan  
**Reviewed by:** Emre / Software Team  
**Date:** 09.12.2025

---

# 1. Objective

Implement the **kinematics layer** for the ENRO mecanum car.  
You already have the **mecanum model** and **map/world** in Gazebo.  
This assignment focuses ONLY on:

- Geometry extraction  
- Inverse kinematics (cmd_vel → wheel speeds)  
- Forward kinematics (wheel speeds → base twist)  
- ROS 2 node that converts `/cmd_vel` to wheel joint commands  
- Testing offline & in simulation  

No PID, controllers, Nav2, localization, or mapping at this stage.

---

# 2. Deliverables

### Mandatory
- `mecanum_kinematics/mecanum_kinematics_node.py`
- `mecanum_kinematics/params/mecanum_kinematics.yaml`
- `mecanum_kinematics/launch/mecanum_kinematics.launch.py`
- `docs/mecanum_kinematics_report.md`

### Optional (Bonus)
- Wheel-speed visualization markers  
- FK debugging topic  
- Diagrams (PDF/PNG) you draw yourself  

---

# 3. Target Directory Structure

```
rk_demo/
 └── mecanum_kinematics/
       ├── mecanum_kinematics_node.py
       ├── launch/
       │     └── mecanum_kinematics.launch.py
       ├── params/
       │     └── mecanum_kinematics.yaml
       └── __init__.py (optional)
docs/
 └── mecanum_kinematics_report.md
Hasan.md   # this assignment
```

---

# 4. Geometry & Parameters

You must extract/confirm from the mecanum model:

- Wheel radius: `R`
- Half-length (`L`) — distance from center to front/back axis
- Half-width (`W`) — distance from center to left/right axis
- Effective offset: `L + W`  

The YAML file should look like:

```yaml
mecanum_kinematics:
  wheel_radius: 0.05
  half_length: 0.20
  half_width: 0.15

  front_left_joint:  wheel_fl_joint
  front_right_joint: wheel_fr_joint
  rear_left_joint:   wheel_rl_joint
  rear_right_joint:  wheel_rr_joint
```

Fill actual joint names from the mecanum model.

---

# 5. Kinematic Equations

## 5.1 Body Velocity (Twist)
- \(v_x\): forward
- \(v_y\): sideways
- \(\omega_z\): yaw angular velocity
# Mecanum Kinematics Equations (Corrected)

## 5.2 Inverse Kinematics (cmd_vel → wheel ω)

```math
\begin{bmatrix}
\omega_1 \
\omega_2 \
\omega_3 \
\omega_4
\end{bmatrix}
=
\frac{1}{R}
\begin{bmatrix}
 1 & -1 & -(L+W) \
 1 &  1 &  (L+W) \
 1 &  1 & -(L+W) \
 1 & -1 &  (L+W)
\end{bmatrix}
\begin{bmatrix}
v_x \
v_y \
\omega_z
\end{bmatrix}
```

## 5.3 Forward Kinematics (wheel ω → base twist)

```math
\begin{bmatrix}
v_x \
v_y \
\omega_z
\end{bmatrix}
=
\frac{R}{4}
\begin{bmatrix}
 1 & 1 & 1 & 1 \
-1 & 1 & 1 & -1 \
-1/(L+W) & 1/(L+W) & -1/(L+W) & 1/(L+W)
\end{bmatrix}
\begin{bmatrix}
\omega_1 \
\omega_2 \
\omega_3 \
\omega_4
\end{bmatrix}
```

---

# 6. ROS 2 Node Requirements

### Node Responsibilities

1. **Subscribe** to `/cmd_vel`  
2. **Compute IK**  
3. **Publish wheel speeds**  
4. (Optional) Publish FK twist for debugging  

---

# 7. Testing & Validation

## 7.1 Offline tests

- Pick test values
- Run IK → FK
- Compare results (error < 5%)

## 7.2 Simulation in Gazebo

Test motions:
- Forward  
- Sideways  
- Rotation  
- Diagonal  

Document results.

---

# 8. Report — mecanum_kinematics_report.md

Include:
- Geometry  
- Equations  
- IK/FK implementation notes  
- Test results  
- How to launch node  

---

# 9. Acceptance Criteria

- [ ] Node runs without errors  
- [ ] Correct wheel velocity outputs  
- [ ] Robot performs all mecanum motions correctly  
- [ ] YAML parameters used (no hard-coding)  
- [ ] Report complete  
- [ ] Code in branch: `feature/mecanum-kinematics-hasan`  

---

# 10. Notes for Hasan

- Don’t guess wheel joint names — read from model.  
- Keep math in matrix form (clean & reliable).  
- Ask Emre if anything is unclear.

---

**End of file.**

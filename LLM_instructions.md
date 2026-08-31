# LLM-Based Robot Action Planning for a Nav2 Mecanum Robot with Manipulator

## Overview

This project integrates a **Large Language Model (LLM)** with a mobile
manipulation robot consisting of:

-   A **mecanum wheeled base** controlled by **Nav2**
-   A **robot arm mounted on the base**
-   A **gripper for cube manipulation**
-   A **perception system detecting cube color and pose**

The goal is to allow a user to issue **natural language commands** like:

> "Put 3 cubes one on top of each other respectively red blue green from
> bottom."

The system converts this command into **structured robot actions** that
execute sequentially.

------------------------------------------------------------------------

# System Architecture

    User Command
         ↓
    LLM Planner Node
         ↓
    Task Manager / Plan Validator
         ↓
    Action Executor (FSM or Behavior Tree)
         ↓
    Nav2 + Arm Controller + Gripper + Perception

The key idea is:

**LLM handles language understanding and planning.** **Robot control
remains deterministic and hard-coded.**

------------------------------------------------------------------------

# Action Library (Hard-Coded Skills)

Define a **fixed set of robot primitives**.\
The LLM is only allowed to use these actions.

Example actions:

-   `go_to_cube(color)`
-   `pick_cube(color)`
-   `go_to_stack_zone()`
-   `place_on_stack(color, level)`

These primitives internally call:

-   **Nav2 navigation**
-   **MoveIt or arm controller**
-   **Gripper control**
-   **Perception queries**

------------------------------------------------------------------------

# Example LLM Output Plan

Input instruction:

> Stack cubes red, blue, green from bottom.

LLM generates a structured plan:

``` json
{
  "goal": "stack_cubes",
  "steps": [
    {"action": "go_to_cube", "args": {"color": "red"}},
    {"action": "pick_cube", "args": {"color": "red"}},
    {"action": "go_to_stack_zone", "args": {}},
    {"action": "place_on_stack", "args": {"color": "red", "level": 1}},

    {"action": "go_to_cube", "args": {"color": "blue"}},
    {"action": "pick_cube", "args": {"color": "blue"}},
    {"action": "go_to_stack_zone", "args": {}},
    {"action": "place_on_stack", "args": {"color": "blue", "level": 2}},

    {"action": "go_to_cube", "args": {"color": "green"}},
    {"action": "pick_cube", "args": {"color": "green"}},
    {"action": "go_to_stack_zone", "args": {}},
    {"action": "place_on_stack", "args": {"color": "green", "level": 3}}
  ]
}
```

------------------------------------------------------------------------

# Task Manager

The **Task Manager Node** performs:

1.  Validate LLM output
2.  Convert symbolic plan into robot calls
3.  Execute steps sequentially
4.  Handle failures and retries

Example execution loop:

``` python
def execute_plan(plan):
    for step in plan:
        success = execute_step(step)
        if not success:
            handle_failure(step)
            return False
    return True
```

------------------------------------------------------------------------

# Primitive Execution Example

Example implementation:

``` python
def execute_step(step):
    action = step["action"]
    args = step["args"]

    if action == "go_to_cube":
        return go_to_cube(args["color"])

    elif action == "pick_cube":
        return pick_cube(args["color"])

    elif action == "go_to_stack_zone":
        return go_to_stack_zone()

    elif action == "place_on_stack":
        return place_on_stack(args["color"], args["level"])

    else:
        raise ValueError("Unknown action")
```

------------------------------------------------------------------------

# Robot Skill Implementations

## go_to_cube(color)

Steps:

1.  Query perception for cube pose
2.  Compute base approach pose
3.  Send goal to Nav2
4.  Wait until reached

------------------------------------------------------------------------

## pick_cube(color)

Steps:

1.  Obtain cube pose
2.  Move arm above cube
3.  Descend
4.  Close gripper
5.  Lift cube
6.  Verify grasp

------------------------------------------------------------------------

## place_on_stack(color, level)

Steps:

1.  Move to stack zone
2.  Compute stack height from level
3.  Move arm to place pose
4.  Open gripper
5.  Retreat

------------------------------------------------------------------------

# World State Representation

Maintain a symbolic state of the environment.

Example:

``` json
{
  "red_cube": {"location": "table", "held": false},
  "blue_cube": {"location": "table", "held": false},
  "green_cube": {"location": "table", "held": false},
  "stack_zone": {"stack": []}
}
```

State updates after each action.

------------------------------------------------------------------------

# Failure Handling

Possible failures:

-   Cube not detected
-   Navigation failure
-   Grasp failure
-   Collision detected

Return structured results:

``` json
{
  "success": false,
  "error": "grasp_failed"
}
```

The task manager may:

-   Retry
-   Replan
-   Abort safely

------------------------------------------------------------------------

# ROS2 Node Structure

Suggested nodes:

-   `llm_planner_node`
-   `task_manager_node`
-   `perception_node`
-   `base_navigation_interface`
-   `arm_controller_interface`
-   `world_state_node`

------------------------------------------------------------------------

# Recommended Development Strategy

### Phase 1

Hard-code task plans without LLM.

### Phase 2

Use LLM for **language → structured goal**.

### Phase 3

Allow LLM to output **symbolic action sequences**.

------------------------------------------------------------------------

# Key Design Principle

**Never let the LLM control motors directly.**

Instead:

    Language → Plan → Validated Actions → Robot Skills

This architecture ensures:

-   Safety
-   Determinism
-   Debuggability
-   Robust execution

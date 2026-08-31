# src/cube_manipulation/cube_manipulation/arm_profiles.py

# Robotik kolun 5 eklemi için açı profilleri [j1, j2, j3, j4, j5]
ARM_PROFILES = {
    "home": [0.0, 0.0, 0.0, 0.0, 0.0],
    
    "red": {
        "pre_grasp":  [0.1, -0.2, 0.3, 0.1, 0.0],
        "grasp":      [0.1, -0.4, 0.5, 0.2, 0.0],
        "lift":       [0.1, -0.1, 0.2, 0.0, 0.0]
    },
    "blue": {
        "pre_grasp":  [-0.1, -0.2, 0.3, 0.1, 0.0],
        "grasp":      [-0.1, -0.4, 0.5, 0.2, 0.0],
        "lift":       [-0.1, -0.1, 0.2, 0.0, 0.0]
    },
    "green": {
        "pre_grasp":  [0.0, -0.2, 0.3, 0.1, 0.0],
        "grasp":      [0.0, -0.4, 0.5, 0.2, 0.0],
        "lift":       [0.0, -0.1, 0.2, 0.0, 0.0]
    },
    
    # Küpleri üst üste dizeceğimiz 'stack' masası (Katlara göre yükseklik ayarlı)
    "stack": {
        "level_1": { # 1. Küp (Zemin)
            "pre_place":  [0.0, -0.2, 0.3, 0.1, 0.0],
            "place":      [0.0, -0.4, 0.5, 0.2, 0.0]
        },
        "level_2": { # 2. Küp (Üst üste koyarken tahtadaki +0.0.5 yüksekliği)
            "pre_place":  [0.0, -0.1, 0.2, 0.1, 0.0],
            "place":      [0.0, -0.3, 0.4, 0.2, 0.0]
        },
        "level_3": { # 3. Küp
            "pre_place":  [0.0, 0.0, 0.1, 0.1, 0.0],
            "place":      [0.0, -0.2, 0.3, 0.2, 0.0]
        }
    }
}
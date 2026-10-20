"""Shared course geometry and finish/checkpoint coordinates, in metres."""
LANES = (-3.6, 3.6)
OUT_Y, RETURN_Y = -1.65, 1.65
FINISH_BASE_X = 1.9
TARGET_X = FINISH_BASE_X-.86
TARGET_DY = RETURN_Y+.35
DECK_START, DECK_END, DECK_HEIGHT = 4.7, 6.1, .285
RAMP_START, RAMP_END = 2.9, 8.3
COURSE_WIDTH = 2.05
CORRIDOR_START, CORRIDOR_END, CORRIDOR_WIDTH = 9.3, 18.1, 1.85
SLALOM_GATES = ((10.5,-1.025),(13.6,-2.275),(16.7,-1.025))
TURN_X=21.6
ROUGH_START, ROUGH_END = 10., 13.2
TUNNEL_START, TUNNEL_END, TUNNEL_CLEARANCE = 6., 7.7, 1.30
STAGE_NAMES = ('Yokuş / köprü', 'Şikan 1: sola', 'Şikan 2: sağa',
               'Şikan 3: sola', '180° dönüş', 'Engebeli dönüş yolu',
               'Alçak geçit', 'Son hizalama')

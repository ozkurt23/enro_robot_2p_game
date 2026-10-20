"""Generate a separate industrial SDF without modifying the legacy Gazebo model."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as E
import xacro
from scipy.spatial.transform import Rotation
from control import JOINTS, Targets

ROOT = Path(__file__).resolve().parents[1]
E.register_namespace('gz', 'http://gazebosim.org/schema')


def el(parent, tag, text=None, **attributes):
    node = E.SubElement(parent, tag, attributes)
    if text is not None:
        node.text = str(text)
    return node


def box(parent, name, pose, size, color, collision=True, friction_coefficient=1.2):
    for tag in (('visual', 'collision') if collision else ('visual',)):
        part = el(parent, tag, name=name if tag=='visual' else name+'_collision')
        el(part, 'pose', pose)
        el(el(el(part, 'geometry'), 'box'), 'size', size)
        if tag == 'visual':
            mat = el(part, 'material')
            el(mat, 'ambient', color)
            el(mat, 'diffuse', color)
        else:
            friction = el(el(el(part, 'surface'), 'friction'), 'ode')
            el(friction, 'mu', friction_coefficient)
            el(friction, 'mu2', friction_coefficient)


def fixed(world, name, xyz, size, color):
    model = el(world, 'model', name=name)
    el(model, 'static', 'true')
    el(model, 'pose', xyz + ' 0 0 0')
    link = el(model, 'link', name='body')
    box(link, 'body', '0 0 0 0 0 0', size, color)
    return model


def plugin(parent, filename, name):
    return el(parent, 'plugin', filename='gz-sim-' + filename + '-system', name='gz::sim::systems::' + name)


def robot():
    xml = xacro.process_file(str(ROOT / 'src/mecanum_robot_description/urdf/mecanum_robot.xacro'),
                            mappings={'use_ros2_control': 'false', 'use_native_control': 'false',
                                      'enable_game_assets': 'false', 'enable_game_camera': 'false'}).toxml()
    # gz sdf accepts stdin only via a file; generated intermediates live in the run directory.
    tree = E.fromstring(xml)
    # Bake a safe initial pose into joint origins; controller coordinates are
    # offsets from this pose. No spawn-time sweep through the floor or cargo.
    for name, initial in zip(JOINTS, Targets().joints()):
        joint = tree.find(f"joint[@name='{name}']")
        origin = joint.find('origin')
        rotation = Rotation.from_euler('xyz', [float(v) for v in origin.get('rpy', '0 0 0').split()])
        axis = [float(v) for v in joint.find('axis').get('xyz').split()]
        if joint.get('type') == 'prismatic':
            xyz = [float(v) for v in origin.get('xyz').split()]
            delta = rotation.apply([v*initial for v in axis])
            origin.set('xyz', ' '.join(str(a+b) for a,b in zip(xyz, delta)))
        else:
            posed = rotation * Rotation.from_rotvec([v*initial for v in axis])
            origin.set('rpy', ' '.join(str(v) for v in posed.as_euler('xyz')))
        limit = joint.find('limit')
        for bound in ('lower', 'upper'):
            if limit is not None and limit.get(bound) is not None:
                limit.set(bound, str(float(limit.get(bound))-initial))
    return E.tostring(tree, encoding='unicode')


def build(directory, player=1):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    urdf = directory / 'robot.urdf'
    urdf.write_text(robot())
    converted = subprocess.run(['gz', 'sdf', '-p', str(urdf)], capture_output=True, text=True, check=True)
    model = E.fromstring(converted.stdout.replace('<sdf ', '<sdf xmlns:gz="http://gazebosim.org/schema" ', 1)).find('model')
    assert model is not None
    model.set('name', 'mobil_manipulator')
    el(model, 'pose', '0 0 .002 0 0 0')
    for joint, initial in zip(JOINTS, Targets().joints()):
        p = plugin(model, 'joint-position-controller', 'JointPositionController')
        for tag, value in {'joint_name': joint, 'topic': f'/manual/{joint}',
                           'initial_position': 0, 'p_gain': 400,
                           'i_gain': 0, 'd_gain': .08,
                           'cmd_max': 12 if 'slider' in joint else .25,
                           'cmd_min': -12 if 'slider' in joint else -.25,
                           'use_velocity_commands': 'false' if 'slider' in joint else 'true'}.items():
            el(p, tag, value)
    p = plugin(model, 'joint-state-publisher', 'JointStatePublisher')
    el(p, 'topic', '/manual/joint_states')
    for joint in JOINTS:
        el(p, 'joint_name', joint)
    # Keep finger dynamics physical, including their weight.
    for name in ('jaw_one_v1_1', 'jaw_two_v1_1'):
        link = model.find(f"link[@name='{name}']")
        if link is not None:
            gravity = link.find('gravity')
            if gravity is not None:
                gravity.text = 'true'
            # URDF conversion can omit named finger collision surfaces. Set
            # friction on the actual SDF contact geometry, not the visual.
            for collision in link.findall('collision'):
                parent = collision
                for tag in ('surface', 'friction', 'ode'):
                    child = parent.find(tag)
                    parent = child if child is not None else el(parent, tag)
                for tag in ('mu', 'mu2'):
                    coefficient = parent.find(tag)
                    if coefficient is None:
                        coefficient = el(parent, tag)
                    coefficient.text = '1.8'
    root = E.Element('sdf', version='1.9')
    world = el(root, 'world', name=f'factory_p{player}')
    phys = el(world, 'physics', name='contact_physics', type='ignored')
    el(phys, 'max_step_size', '.001')
    el(phys, 'real_time_factor', '1')
    plugin(world, 'physics', 'Physics')
    plugin(world, 'user-commands', 'UserCommands')
    plugin(world, 'scene-broadcaster', 'SceneBroadcaster')
    plugin(world, 'contact', 'Contact')
    el(world, 'gravity', '0 0 -9.81')
    scene = el(world, 'scene')
    el(scene, 'ambient', '.55 .55 .55 1')
    el(scene, 'background', '.55 .60 .65 1')
    sun = el(world, 'light', name='factory_lighting', type='directional')
    el(sun, 'pose', '0 0 8 0 0 0')
    el(sun, 'direction', '-.3 .4 -1')
    el(sun, 'diffuse', '.85 .85 .85 1')
    el(sun, 'cast_shadows', 'true')
    fixed(world, 'concrete_floor', '2 1 -.1', '16 13 .2', '.43 .45 .46 1')
    fixed(world, 'back_wall', '2 7 2', '16 .2 4', '.64 .66 .67 1')
    fixed(world, 'side_wall', '10 1 2', '.2 12 4', '.64 .66 .67 1')
    for x in (-5, 0, 5, 9.7):
        fixed(world, f'steel_column_{x}', f'{x} 6.7 2', '.22 .22 4', '.24 .28 .3 1')
    for y in (-1.6, 1.1, 4.3):
        fixed(world, f'aisle_line_{y}', f'2 {y} .002', '12 .06 .004', '.85 .65 .08 1')
    for x in (-3, 1, 5):
        for level in (.2, 1.2, 2.2):
            fixed(world, f'rack_{x}_{level}', f'{x} 5.9 {level}', '2.8 .9 .09', '.16 .25 .32 1')
            for n in range(3):
                fixed(world, f'stock_{x}_{level}_{n}', f'{x-1+n} 5.9 {level+.26}', '.6 .65 .45', '.52 .35 .19 1')
        for dx in (-1.4, 1.4):
            fixed(world, f'rack_post_{x}_{dx}', f'{x+dx} 5.9 1.35', '.07 .95 2.7', '.73 .32 .10 1')
    for name, x, y in (('pickup', 1.08, -.575), ('delivery', 4.08, 2.425)):
        fixed(world, name+'_bench', f'{x} {y} .8175', '.60 .60 .08', '.24 .29 .32 1')
        for dx in (-.19, .19):
            for dy in (-.27, .27):
                fixed(world, f'{name}_leg_{dx}_{dy}', f'{x+dx} {y+dy} .39', '.055 .055 .78', '.22 .25 .27 1')
    fixed(world, 'delivery_mark', '3.86 2.65 .8585', '.3 .3 .002', '.18 .48 .22 1')
    # Real moving surface: Harmonic TrackController, as in Gazebo's conveyor.sdf.
    belt = fixed(world, 'conveyor', '3 -3 .78', '4 .7 .12', '.10 .11 .12 1')
    p = plugin(belt, 'track-controller', 'TrackController')
    el(p, 'link', 'body')
    el(p, 'velocity_topic', '/belt/speed')
    el(p, 'max_command_age', '.5')
    for y in (-3.4, -2.6):
        fixed(world, f'belt_rail_{y}', f'3 {y} .82', '4 .06 .2', '.6 .62 .64 1')
    for x in (1.2, 4.8):
        fixed(world, f'belt_leg_{x}', f'{x} -3 .36', '.12 .75 .72', '.3 .33 .35 1')
    for name, x, y, z, size, mass in [('cargo', .86, -.35, .8985, .08, .12),
                                     ('belt_carton', 2, -3, 1.00, .3, .5)]:
        cargo = el(world, 'model', name=name)
        el(cargo, 'pose', f'{x} {y} {z} 0 0 0')
        link = el(cargo, 'link', name='box')
        inertial = el(link, 'inertial')
        el(inertial, 'mass', mass)
        inertia = el(inertial, 'inertia')
        for axis in ('ixx', 'iyy', 'izz'):
            el(inertia, axis, mass*size*size/6)
        box(link, 'cardboard', '0 0 0 0 0 0', f'{size} {size} {size}', '.58 .39 .20 1',
            friction_coefficient=1.8 if name == 'cargo' else 1.2)
        box(link, 'packing_tape', f'0 0 {size/2+.0002} 0 0 0', f'{size*.18} {size} .0004', '.75 .61 .38 1', False)
        p = plugin(cargo, 'odometry-publisher', 'OdometryPublisher')
        el(p, 'odom_topic', f'/{name}/odom')
        el(p, 'dimensions', 3)
        el(p, 'odom_publish_frequency', 30)
    world.append(model)
    # Native Gazebo widgets; no custom game renderer.
    config = Path('/opt/ros/jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/gui/gui.config').read_text()
    gui = el(world, 'gui', fullscreen='false')
    wrapper = E.fromstring('<config>' + config.replace('<?xml version="1.0"?>', '') + '</config>')
    for item in wrapper:
        if item.tag == 'plugin':
            camera = item.find('camera_pose')
            if camera is not None:
                camera.text = '-3.3 -4.2 3.2 0 .42 .7'
            gui.append(item)
    E.indent(root)
    out = directory / f'factory_p{player}.sdf'
    E.ElementTree(root).write(out, encoding='unicode', xml_declaration=True)
    return out

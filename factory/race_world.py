"""One authoritative factory, two physical robots and player-specific GUI files."""
from copy import deepcopy
from pathlib import Path
import math
import xml.etree.ElementTree as E
from world import build, el, fixed, plugin

from course import LANES, TARGET_X, TARGET_DY, OUT_Y


def beam(world, name, x0, x1, y, z0, z1, width, thickness, color):
    angle = math.atan2(z1-z0,x1-x0)
    length = math.hypot(x1-x0,z1-z0)
    item=fixed(world,name,f'{(x0+x1)/2} {y} {(z0+z1)/2-thickness*math.cos(angle)/2}',
               f'{length} {width} {thickness}',color)
    pose=item.find('pose').text.split()
    pose[4]=str(-angle)
    item.find('pose').text=' '.join(pose)
    return item




def shift(model, dx=0., dy=0.):
    pose = model.find('pose')
    if pose is None:
        pose = el(model, 'pose', '0 0 0 0 0 0')
    values = [float(x) for x in pose.text.split()]
    values[0] += dx
    values[1] += dy
    pose.text = ' '.join(map(str, values))


def build_race(directory, detailed=True):
    directory = Path(directory)
    tree = E.parse(build(directory/'source'))
    world = tree.find('world')
    world.set('name', 'factory_race')
    floor=world.find("model[@name='concrete_floor']")
    floor.find('pose').text='10 0 -.1 0 0 0'
    for size in floor.findall('.//box/size'): size.text='32 26 .2'
    world.find("model[@name='side_wall']/pose").text='26 0 2 0 0 0'
    back=world.find("model[@name='back_wall']")
    back.find('pose').text='10 13 2 0 0 0'
    for size in back.findall('.//box/size'):size.text='32 .2 4'
    for m in list(world.findall('model')):
        if m.get('name').startswith('aisle_line_'): world.remove(m)
    # Keep the established grasp geometry, masses, controllers and friction.
    robot = world.find("model[@name='mobil_manipulator']")
    cargo = world.find("model[@name='cargo']")
    stations = [m for m in world.findall('model') if m.get('name').startswith(('pickup_', 'delivery_'))]
    for item in [robot, cargo, *stations]:
        world.remove(item)
    for player, lane in enumerate(LANES, 1):
        prefix = f'/p{player}'
        rob = deepcopy(robot)
        rob.set('name', f'robot_p{player}')
        shift(rob, dy=lane+OUT_Y)
        for tag in ('topic', 'odom_topic', 'tf_topic'):
            for node in rob.findall('.//'+tag):
                if node.text and node.text.startswith('/'):
                    node.text = prefix + node.text
        odom = plugin(rob, 'odometry-publisher', 'OdometryPublisher')
        el(odom, 'odom_topic', prefix+'/physical_odom')
        el(odom, 'dimensions', 3)
        el(odom, 'odom_publish_frequency', 30)
        tint = '.15 .40 .80 1' if player == 1 else '.85 .35 .10 1'
        body = rob.find("link[@name='base_footprint']")
        for visual in body.findall('visual'):
            if 'base_link' in visual.get('name', ''):
                for color in visual.findall('material/diffuse') + visual.findall('material/ambient'):
                    color.text = tint
        world.append(rob)
        obj = deepcopy(cargo)
        obj.set('name', f'cargo_p{player}')
        shift(obj, dy=lane+OUT_Y)
        obj.find('plugin/odom_topic').text = prefix+'/cargo/odom'
        tape = obj.find("link/visual[@name='packing_tape']/material")
        for color in list(tape):
            color.text = tint
        world.append(obj)
        for station in stations:
            item = deepcopy(station)
            item.set('name', f'p{player}_'+station.get('name'))
            # Reflect the source layout for a west-facing return-lane delivery.
            delivery = station.get('name').startswith('delivery_')
            if delivery:
                pose=[float(v) for v in item.find('pose').text.split()]
                pose[0]=TARGET_X-(pose[0]-3.86)
                pose[1]=lane+TARGET_DY-(pose[1]-2.65)
                pose[5]+=math.pi
                item.find('pose').text=' '.join(map(str,pose))
            else:
                shift(item,dy=lane+OUT_Y)
            if station.get('name') == 'delivery_mark':
                for node in item.findall('.//box/size'):
                    node.text = '.20 .20 .002'
                for node in item.findall('.//material/diffuse')+item.findall('.//material/ambient'):
                    node.text = tint
            world.append(item)
            if station.get('name').endswith('_bench'):
                pose = [float(v) for v in item.find('pose').text.split()]
                # A solid, visible industrial cabinet prevents wheels/chassis
                # slipping under the thin tabletop between narrow table legs.
                fixed(world, f'p{player}_'+station.get('name')+'_cabinet',
                      f'{pose[0]} {pose[1]} .39', '.60 .60 .78', '.29 .34 .37 1')
        from winding import build_course
        build_course(world,player,lane,tint,beam)
    # Central maintenance trench props and overhead pipework retain a real
    # industrial test-track appearance without hiding the opponent behind walls.
    for x in (3.,7.,11.,15.,20.,24.):
        fixed(world,f'overhead_pipe_{x}',f'{x} 0 3.4','.16 10 .16','.52 .30 .12 1')
        for y in (-5.,5.):
            fixed(world,f'pipe_stanchion_{x}_{y}',f'{x} {y} 1.7','.12 .12 3.4','.27 .3 .33 1')
    # Move conveyor out of both driving lanes. It remains a real contact belt.
    for model in world.findall('model'):
        if model.get('name').startswith(('conveyor', 'belt_')):
            shift(model, dy=-6.4)
    if detailed:
        from facility import design
        design(world,directory)
    gui = world.find('gui')
    world.remove(gui)
    configs = []
    for player in (1, 2):
        config = E.Element('config')
        window = el(config, 'window')
        el(window, 'width', 1150)
        el(window, 'height', 850)
        el(window, 'dialog_on_exit', 'false')
        for original in gui:
            # Shared /gui/track commands would move both windows. Use a renderer-
            # local plugin subscribed only to this player's zoom instead.
            if original.get('filename') in ('MinimalScene','GzSceneManager','InteractiveViewControl','MarkerManager'):
                config.append(deepcopy(original))
        custom = el(config, 'plugin', filename='PlayerCamera', name=f'Oyuncu {player}')
        el(custom, 'player', player)
        el(custom, 'ready_file', str(directory/f'p{player}-camera.ready'))
        props = el(custom, 'gz-gui')
        el(props, 'property', 'floating', type='string', key='state')
        el(props, 'property', 'false', type='bool', key='showTitleBar')
        path = directory/f'player{player}.config'
        path.write_text('\n'.join(E.tostring(child, encoding='unicode') for child in config))
        configs.append(path)
    E.indent(tree)
    path = directory/'factory_race.sdf'
    tree.write(path, encoding='unicode', xml_declaration=True)
    return path, configs

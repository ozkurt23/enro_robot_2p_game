"""Check recorded real Gazebo evidence, not return codes or fabricated success."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as E


def verify(directory, kind):
    directory = Path(directory)
    for sdf in directory.glob('p*/factory_p*.sdf'):
        root = E.parse(sdf)
        plugins = [p.get('name', '') for p in root.findall('.//plugin')]
        assert not any('Detach' in p or 'Attach' in p for p in plugins)
        assert root.find(".//model[@name='cargo']/link/inertial/mass").text == '0.12'
    data = [json.loads(s) for s in (directory/'p1-status.jsonl').read_text().splitlines()]
    def near(t):
        return min(data, key=lambda row: abs(row['age']-t))
    start, lifted = near(8), near(18)
    assert lifted['cargo'][2] - start['cargo'][2] > .1, 'Cargo did not physically lift'
    if kind in ('drop', 'isolation'):
        carried, released = near(23), near(32)
        assert carried['base'][1] > .5
        assert abs((carried['cargo'][1]-carried['base'][1]) - start['cargo'][1]) < .06
        assert carried['cargo'][2] > 1., 'Cargo slipped before release'
        assert released['cargo'][2] < .1, 'Open fingers did not release cargo'
    if kind == 'delivery':
        for p in (1, 2):
            final = json.loads((directory/f'p{p}-status.json').read_text())
            assert final['delivered']
            assert math.dist(final['cargo'], [3.86, 2.65, .8975]) < .08
            assert final['belt_box'][0] > 2.5, 'Conveyor did not transport its carton'
    if kind == 'isolation':
        other = json.loads((directory/'p2-status.json').read_text())
        assert math.dist(other['base'][:3], [0, 0, 0]) < .01, 'Player 1 moved player 2'
        assert math.dist(other['cargo'], [.86, -.35, .8975]) < .01
    print('PHYSICS_ACCEPTANCE_OK', kind, directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--kind', choices=('drop', 'delivery', 'isolation'), required=True)
    args = parser.parse_args()
    verify(args.directory, args.kind)

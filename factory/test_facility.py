"""Art budgets, reproducible meshes and unchanged two-player physical track."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as E
import numpy as np
from race_world import build_race


class FacilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='enro-facility-test-')
        root=Path(cls.temp.name)
        cls.baseline=E.parse(build_race(root/'baseline',detailed=False)[0]).find('world')
        cls.directory=root/'candidate'
        cls.world=E.parse(build_race(cls.directory)[0]).find('world')
        cls.manifest=json.loads((cls.directory/'facility_assets/manifest.json').read_text())

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_gameplay_and_robot_physics_unchanged(self):
        for model in self.baseline.findall('model'):
            name=model.get('name')
            if name.startswith(('p1_','p2_','robot_','cargo_','conveyor','belt_')):
                candidate=self.world.find(f"model[@name='{name}']")
                self.assertIsNotNone(candidate,name)
                self.assertEqual(E.tostring(model),E.tostring(candidate),name)
        self.assertEqual(E.tostring(self.baseline.find('physics')),E.tostring(self.world.find('physics')))

    def test_new_colliders_do_not_intrude_into_race_envelope(self):
        for item in self.manifest['colliders']:
            x,y,z=item['center'];dx,dy,dz=item['size']
            # Entire dual lane, pickup clearance and destination approach.
            overlap_x=x+dx/2>-2 and x-dx/2<24
            overlap_y=y+dy/2>-7 and y-dy/2<7
            self.assertFalse(overlap_x and overlap_y and z-dz/2<2.8,item['name'])

    def test_bounded_visual_cost_and_offline_resources(self):
        self.assertLess(self.manifest['triangles'],100000)
        self.assertLessEqual(self.manifest['materials'],18)
        self.assertLess(len(self.manifest['colliders']),55)
        detail=self.world.find("model[@name='facility_detail']")
        self.assertEqual(len(detail.findall('link')),1)
        self.assertEqual(len(detail.findall('.//visual')),self.manifest['materials'])
        self.assertEqual(detail.find('static').text,'true')
        self.assertEqual(detail.findall('plugin'),[])
        for uri in detail.findall('.//uri'):
            self.assertTrue(uri.text.startswith('file://'))
            self.assertTrue(Path(uri.text[7:]).is_file())

    def test_stl_is_finite_non_degenerate_and_consistent(self):
        total=0
        for path in (self.directory/'facility_assets').glob('*.stl'):
            data=path.read_bytes();count=struct.unpack_from('<I',data,80)[0]
            self.assertEqual(len(data),84+50*count)
            total+=count
            for offset in range(84,len(data),50):
                values=struct.unpack_from('<12fH',data,offset)
                self.assertTrue(all(np.isfinite(values[:12])))
                self.assertAlmostEqual(np.linalg.norm(values[:3]),1.,places=5)
        self.assertEqual(total,self.manifest['triangles'])

    def test_offline_generation_is_deterministic(self):
        directory=Path(self.temp.name)/'repeat'
        build_race(directory)
        for path in (self.directory/'facility_assets').glob('*.stl'):
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),hashlib.sha256((directory/'facility_assets'/path.name).read_bytes()).digest())

    def test_signage_covers_winding_stages_and_instructions(self):
        labels=self.manifest['labels']
        for label in ('01 / RAMP','02-04 / SLALOM','05 / U TURN','06 / TERRAIN','07 / LOW 1.3M','08 / DELIVERY','LOWER ARM','DELIVERY'):
            self.assertEqual(labels.count(label),2 if label in ('LOWER ARM','DELIVERY') else 4)

    def test_unique_link_child_names_and_valid_pbr_ranges(self):
        for link in self.world.findall('.//link'):
            names=[child.get('name') for child in link if child.get('name')]
            self.assertEqual(len(names),len(set(names)),link.get('name'))
        detail=self.world.find("model[@name='facility_detail']")
        for material in detail.findall('.//material'):
            for tag in ('roughness','metalness'):
                value=float(material.find('pbr/metal/'+tag).text)
                self.assertGreaterEqual(value,0);self.assertLessEqual(value,1)


if __name__=='__main__':unittest.main()

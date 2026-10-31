import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("planner",ROOT/"scripts/planner.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASE=dict(project="測試",version="v1",date="2026-11-01",width="6m",throw_ratio=1.2,aspect="16:9",resolution="Full HD")

def calc(**kw): return m.calculate(BASE|kw)
class PlannerTests(unittest.TestCase):
    def test_A(self):
        r=calc();self.assertAlmostEqual(r['distance'],7.2);self.assertAlmostEqual(r['height'],3.375)
        self.assertAlmostEqual(r['pitch_mm'],3.125);self.assertAlmostEqual(r['diagonal_m'],(36+3.375**2)**.5)
    def test_B(self):
        b=BASE|dict(distance="5m",throw_ratio=1.25,aspect="16:10",resolution="WUXGA");b.pop('width')
        r=m.calculate(b);self.assertEqual(r['width'],4);self.assertEqual(r['height'],2.5)
    def test_C(self):
        d=BASE|dict(lens=[1.2,1.8],position="6m");d.pop('throw_ratio');r=m.calculate(d)
        self.assertAlmostEqual(r['interval'][0],7.2);self.assertAlmostEqual(r['interval'][1],10.8)
        self.assertFalse(r['position_valid']);self.assertIsNone(r['distance']);self.assertTrue(r['warnings'])
    def test_range_endpoints(self):
        for pos in ('7.2m','10.8m'):
            r=calc(lens=[1.2,1.8],distance=pos,throw_ratio=m.length(pos)/6);self.assertTrue(r['position_valid'])
    def test_required_ratio(self):
        d=BASE|dict(distance="9m");d.pop('throw_ratio');self.assertEqual(m.calculate(d)['throw_ratio'],1.5)
    def test_units(self):
        for v in ('6m','600cm','6000mm','6公尺','600公分','6000毫米'):
            with self.subTest(v=v): self.assertEqual(m.length(v),6)
    def test_ratio_presets_custom(self):
        for a,res,h in [('16:9','Full HD',3.375),('16:10','WUXGA',3.75),('4:3',[1600,1200],4.5),('2:1',[2000,1000],3)]:
            with self.subTest(a=a):self.assertEqual(calc(aspect=a,resolution=res)['height'],h)
    def test_4k(self): self.assertEqual(calc(resolution='4K UHD')['pitch_mm'],1.5625)
    def test_infer_aspect(self):
        d=dict(BASE);d.pop('aspect');self.assertAlmostEqual(m.calculate(d)['aspect'],16/9)
    def test_letterbox(self):
        r=calc(aspect='16:10',resolution='WUXGA',content_aspect='16:9')
        self.assertEqual(r['content_width'],6);self.assertEqual(r['content_height'],3.375);self.assertEqual(r['bars_each_m'],[0,.1875])
    def test_pillarbox(self):
        r=calc(content_aspect='4:3');self.assertEqual(r['content_width'],4.5);self.assertEqual(r['bars_each_m'],[.75,0])
    def test_cover(self):
        r=calc(content_aspect='4:3',fit='cover');self.assertEqual(r['content_width'],6);self.assertEqual(r['crop_each_m'],[0,.5625]);self.assertTrue(r['warnings'])
    def test_stretch(self):self.assertTrue(calc(fit='stretch')['warnings'])
    def test_invalid_values(self):
        for bad in ('0m','-1m','NaNm','Infinitym','1ft','6',6,True):
            with self.subTest(bad=bad),self.assertRaises(m.InputError):calc(width=bad)
    def test_invalid_ratios(self):
        for bad in ('0:1','-1:2','1000:1','1:0','1:2:3',True):
            with self.subTest(bad=bad),self.assertRaises(m.InputError):calc(aspect=bad)
    def test_contradictions(self):
        for kw in [dict(distance='6m'),dict(height='5m'),dict(position='8m'),dict(aspect='4:3'),dict(lens=[1.8,1.2]),dict(resolution=[1920,True])]:
            with self.subTest(kw=kw),self.assertRaises(m.InputError):calc(**kw)
    def test_missing(self):
        for keys in [('width',),('resolution',),('project',),('width','throw_ratio')]:
            d=dict(BASE)
            for k in keys:d.pop(k)
            with self.subTest(keys=keys),self.assertRaises(m.InputError):m.calculate(d)
    def test_unknown_geometry_and_field(self):
        for kw in [dict(geometry='ust'),dict(geometry='tilted'),dict(garbage=3),dict(throw_ratio=float('nan')),dict(date='2026-99-01'),dict(date='20261101'),dict(fit='auto'),dict(notes='bad')]:
            with self.subTest(kw=kw),self.assertRaises(m.InputError):calc(**kw)
    def test_consistency_tolerance(self):self.assertAlmostEqual(calc(distance='7.200000001m')['distance'],7.2)
    def test_repeatable(self):
        self.assertEqual(m.render(calc()),m.render(calc()));self.assertEqual(m.markdown(calc()),m.markdown(calc()))
    def test_fixed_panels_and_scale(self):
        panels=[]
        for name in 'ABC':
            r=m.calculate(json.loads((ROOT/f'examples/{name}.input.json').read_text()))
            tree=ET.fromstring(m.render(r));panels.append([(e.get('id'),e.get('x'),e.get('y'),e.get('width'),e.get('height')) for e in tree.iter() if e.get('id','').endswith('-panel')])
            self.assertEqual(tree.get('viewBox'),'0 0 1600 1000');self.assertIn('俯視等比',m.render(r));self.assertIn('正視等比',m.render(r))
        self.assertEqual(panels[0],panels[1]);self.assertEqual(panels[1],panels[2])
    def test_long_text_and_xml_escape(self):
        name='專案<&>測試'*100;r=calc(project=name,version='版本'*80,notes=['備註'*500])
        svg=m.render(r);tree=ET.fromstring(svg);self.assertIn('…',svg);self.assertIn('全文見',svg)
        self.assertIn('完整備註請見',svg);self.assertIn('專案&lt;&amp;&gt;',m.markdown(r))
        self.assertLess(len([e for e in tree.iter() if e.tag.endswith('text')]),65)
    def test_cli_bad_input_creates_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'bad.json').write_text('{}')
            run=subprocess.run([sys.executable,str(ROOT/'scripts/planner.py'),str(p/'bad.json'),'--output',str(p/'out')],capture_output=True)
            self.assertEqual(run.returncode,2);self.assertFalse((p/'out.svg').exists())
    def test_cli_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            args=[sys.executable,str(ROOT/'scripts/planner.py'),str(ROOT/'examples/A.input.json'),'--output',str(Path(d)/'result')]
            self.assertEqual(subprocess.run(args,capture_output=True).returncode,0)
            self.assertEqual(subprocess.run(args,capture_output=True).returncode,2)
            self.assertEqual(len(list(Path(d).iterdir())),3)
if __name__=='__main__':unittest.main(verbosity=2)

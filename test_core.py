import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from app import DEFAULTS, load_settings, save_settings
from telemetry import Sampler
from dashboard import fmt, storage


class CoreTests(unittest.TestCase):
    def test_invalid_config_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            for raw in ('{broken','[]','null','{"font_scale":99,"text_opacity":-1,"modules":{"cpu":false,"unknown":true}}'):
                path.write_text(raw,encoding='utf-8')
                value=load_settings(path)
                self.assertEqual(value['font_scale'],1.)
                self.assertEqual(value['text_opacity'],100)
                self.assertNotIn('unknown',value['modules'])
            data=copy.deepcopy(DEFAULTS);data['monitor']='DISPLAY2';data['font_scale']=1.15
            save_settings(path,data)
            self.assertEqual(load_settings(path),data)

    def test_missing_is_not_zero(self):
        self.assertEqual(fmt(None,'%'),'—')
        self.assertEqual(fmt(0,'%'),'0%')
        self.assertEqual(storage(None),'—')
        self.assertEqual(storage(0),'0.0 GB')

    def test_cpu_baseline_and_resume(self):
        with patch('telemetry.psutil.cpu_percent',return_value=37):
            sampler=Sampler()
            sampler.gpu_sample=lambda now:{}
            sampler.application_sample=lambda:[]
            with patch('telemetry.psutil.virtual_memory',return_value=Mock(_asdict=lambda:{'percent':50})):
                self.assertIsNone(sampler.sample(100).cpu)
                self.assertEqual(sampler.sample(101).cpu,37)
                self.assertIsNone(sampler.sample(200).cpu)
                self.assertEqual(sampler.sample(201).cpu,37)
                sampler.reset()
                self.assertIsNone(sampler.sample(202).cpu)

    def test_application_family_cpu_normalization(self):
        parent=Mock(pid=123)
        parent.exe.return_value=r'C:\apps\chrome.exe'
        parent.create_time.return_value=10
        parent.cpu_percent.return_value=40
        parent.memory_info.return_value=Mock(rss=100)
        child=Mock(pid=124)
        child.create_time.return_value=10
        child.cpu_percent.return_value=60
        child.memory_info.return_value=Mock(rss=200)
        parent.children.return_value=[child]
        with patch('telemetry.psutil.cpu_percent'),patch('telemetry.psutil.Process',return_value=parent),patch('telemetry.psutil.cpu_count',return_value=20),patch('telemetry.open_apps',return_value=[dict(pid=123,foreground=True)]):
            sampler=Sampler()
            first=sampler.application_sample()[0]
            self.assertIsNone(first['cpu'])
            second=sampler.application_sample()[0]
            self.assertEqual(second['cpu'],5.)
            self.assertEqual(second['memory'],300)
            self.assertEqual(second['name'],'Google Chrome')
            self.assertTrue(second['foreground'])

    def test_closed_application_is_removed(self):
        with patch('telemetry.psutil.cpu_percent'),patch('telemetry.open_apps',return_value=[]):
            sampler=Sampler();sampler.app_processes={(123,10):Mock()}
            self.assertEqual(sampler.application_sample(),[])
            self.assertEqual(sampler.app_processes,{})


if __name__=='__main__':unittest.main(verbosity=2)

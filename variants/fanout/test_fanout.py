import unittest
import tempfile
import io
from threading import Event
from unittest.mock import Mock, patch
from pathlib import Path
from fanout import clean_code, syntax_check
from client import complete


class FenceRegression(unittest.TestCase):
    def test_inline_function_fence_keeps_signature(self):
        self.assertEqual(clean_code('```function part3(ctx){\nreturn 1;\n}\n```'), 'function part3(ctx){\nreturn 1;\n}')

    def test_language_fence_and_plain_code(self):
        for source in ('```javascript\nfunction part0(ctx){}\n```', 'function part0(ctx){}'):
            self.assertEqual(clean_code(source), 'function part0(ctx){}')

    def test_json_fence(self):
        self.assertEqual(clean_code('```json\n{"parts": []}\n```'), '{"parts": []}')

    def test_undefined_animation_variable_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'part5.js'
            with self.assertRaisesRegex(ValueError, 'mist2Mat'):
                syntax_check('function part5(ctx){ addUpdate(() => { mist2Mat.opacity = 0.1; }); }', path)
            syntax_check('function part5(ctx){ const mist2 = {material:{opacity:0}}; addUpdate(() => { mist2.material.opacity = 0.1; }); }', path)

    def test_component_cannot_override_global_fog(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Fog belongs'):
                syntax_check('function part6(ctx){ scene.fog = null; }', Path(folder)/'part6.js')

    def test_terrain_duplicate_flat_cap_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'matching closed cap'):
                syntax_check('function part4(ctx){ scene.add(new THREE.Mesh(new THREE.CircleGeometry(1,48))); }',Path(folder)/'part4.js',4)


class OrderedAdmission(unittest.TestCase):
    def test_preflight_failure_releases_next_request(self):
        following = Event()
        with tempfile.TemporaryDirectory() as folder, patch('client.urllib.request.build_opener') as build:
            build.return_value.open.side_effect = OSError('tokenizer unavailable')
            with self.assertRaisesRegex(OSError, 'tokenizer unavailable'):
                complete([], Path(folder) / 'part', admission=(Event(), following))
        self.assertTrue(following.is_set())

    def test_admission_timeout_releases_next_and_never_generates(self):
        previous, following = Mock(), Event()
        previous.wait.return_value = False
        with tempfile.TemporaryDirectory() as folder, patch('client.urllib.request.build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(b'{"count": 10, "max_model_len": 4096}')
            with self.assertRaisesRegex(RuntimeError, 'ordered request admission'):
                complete([], Path(folder) / 'part', admission=(previous, following))
            self.assertEqual(build.return_value.open.call_count, 1)
        previous.wait.assert_called_once_with(timeout=60)
        self.assertTrue(following.is_set())


if __name__ == '__main__':
    unittest.main()

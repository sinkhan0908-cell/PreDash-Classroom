import ast
from pathlib import Path
import unittest


tree = ast.parse(Path('predash/classroom.py').read_text())
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_settings')
scope = {'FIELDS': ('key', 'secret', 'cano', 'product')}
exec(compile(ast.Module(body=[fn], type_ignores=[]), 'classroom.py', 'exec'), scope)
resolve = scope['resolve_settings']


class ClassroomSettingsTests(unittest.TestCase):
    def secrets(self, mode='demo', prefix='KIS_'):
        return {'KIS_ENV': mode, prefix+'APP_KEY': 'testkey', prefix+'APP_SECRET': 'testsecret',
                prefix+'CANO': '12345678', prefix+'ACNT_PRDT_CD': '01'}

    def test_secrets_only(self):
        got = resolve({}, self.secrets())
        self.assertEqual(got['mode'], 'demo')
        self.assertEqual(got['key'], 'testkey')

    def test_session_only_and_priority(self):
        session = dict(mode='real', key='screen', secret='secret', cano='87654321', product='01')
        self.assertEqual(resolve(session, {})['key'], 'screen')
        self.assertEqual(resolve(session, self.secrets())['mode'], 'real')

    def test_partial_inputs_never_mix_sources(self):
        secret = self.secrets()
        secret.pop('KIS_APP_KEY')
        got = resolve(dict(mode='demo', key='screen'), secret)
        self.assertFalse(got['key'])
        self.assertFalse(got['secret'])

    def test_incomplete_session_uses_complete_secrets(self):
        self.assertEqual(resolve(dict(mode='demo', key='screen'), self.secrets())['key'], 'testkey')

    def test_demo_request_never_uses_real_keys(self):
        self.assertFalse(resolve({}, self.secrets('real'), 'demo')['key'])
        got = resolve({}, {**self.secrets('real'), **self.secrets('real', 'KIS_DEMO_')}, 'demo')
        self.assertEqual(got['mode'], 'demo')
        self.assertEqual(got['key'], 'testkey')

    def test_real_request_never_uses_demo_keys(self):
        self.assertFalse(resolve({}, self.secrets('demo'), 'real')['key'])

    def test_partial_demo_prefix_never_uses_other_account(self):
        self.assertFalse(resolve({}, {**self.secrets(), 'KIS_DEMO_APP_KEY':'partial'}, 'demo')['key'])


if __name__ == '__main__':
    unittest.main()

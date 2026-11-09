import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
from server import Server


class FileSharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Server(('127.0.0.1', 0), Path(self.temp.name), 'test-code')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, header=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Cookie': self.cookie}
        if header:
            headers['X-LAN-Shelf'] = '1'
        if isinstance(body, dict):
            body = json.dumps(body)
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        status, data = response.status, response.read()
        if response.getheader('Set-Cookie'):
            self.cookie = response.getheader('Set-Cookie').split(';')[0]
        connection.close()
        return status, data

    def login(self):
        self.assertEqual(self.request('POST', '/api/login', {'code': 'test-code'})[0], 200)

    def test_authentication(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertEqual(self.request('GET', '/api/files')[0], 401)
        self.assertEqual(self.request('POST', '/api/login', {'code': 'wrong'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'code': 'test-code'}, False)[0], 403)
        self.login()
        self.assertTrue(json.loads(self.request('GET', '/api/session')[1])['authenticated'])

    def test_transfer_and_duplicate_preservation(self):
        self.login()
        self.assertEqual(self.request('POST', '/api/folder', {'path': '', 'name': 'Docs'})[0], 201)
        content = bytes(range(256)) * 8192
        self.assertEqual(self.request('POST', '/api/upload?path=Docs&name=example.bin', content)[0], 201)
        self.assertEqual(self.request('POST', '/api/upload?path=Docs&name=example.bin', b'new')[0], 201)
        self.assertEqual(self.request('GET', '/api/download?path=Docs/example.bin'), (200, content))
        listing = json.loads(self.request('GET', '/api/files?path=Docs')[1])['files']
        self.assertEqual({f['name'] for f in listing}, {'example.bin', 'example (1).bin'})
        self.assertFalse(list(Path(self.temp.name).rglob('.lan-upload-*')))

    def test_invalid_paths_and_names(self):
        self.login()
        self.assertEqual(self.request('GET', '/api/files?path=..')[0], 400)
        self.assertEqual(self.request('GET', '/api/download?path=../server.py')[0], 400)
        self.assertEqual(self.request('POST', '/api/upload?name=..%2Fevil', b'bad')[0], 400)
        self.assertEqual(self.request('POST', '/api/upload?name=CON', b'bad')[0], 400)
        self.assertEqual(self.request('POST', '/api/folder', {'name': '../escape'})[0], 400)
        self.assertEqual(self.request('POST', '/api/upload?name=empty.txt', b'')[0], 201)
        self.assertEqual(self.request('GET', '/api/download?path=empty.txt'), (200, b''))

    def test_folder_transfer_and_zip(self):
        self.assertEqual(self.request('GET', '/api/download?path=Docs')[0], 401)
        self.login()
        for name in ('Docs', 'Docs (1)'):
            status, body = self.request('POST', '/api/folder', {'name': 'Docs', 'unique': True})
            self.assertEqual(status, 201)
            self.assertEqual(json.loads(body)['name'], name)
        self.assertEqual(self.request('POST', '/api/folder', {'path': 'Docs', 'name': 'Nested'})[0], 201)
        self.assertEqual(self.request('POST', '/api/folder', {'path': 'Docs', 'name': 'Empty'})[0], 201)
        self.assertEqual(self.request('POST', '/api/upload?path=Docs/Nested&name=test.txt', b'contents')[0], 201)
        (self.server.root / 'Docs' / '.lan-upload-private').write_bytes(b'incomplete')
        status, body = self.request('GET', '/api/download?path=Docs')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {'Docs/', 'Docs/Nested/', 'Docs/Empty/', 'Docs/Nested/test.txt'})
            self.assertEqual(archive.read('Docs/Nested/test.txt'), b'contents')

    def test_login_throttle_and_session_expiration(self):
        self.login()
        with self.server.lock:
            self.server.sessions = {token: 0 for token in self.server.sessions}
        self.assertEqual(self.request('GET', '/api/files')[0], 401)
        for _ in range(9):
            self.assertEqual(self.request('POST', '/api/login', {'code': 'wrong'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'code': 'test-code'})[0], 429)

    def test_non_object_json(self):
        self.assertEqual(self.request('POST', '/api/login', '[]')[0], 400)
        self.login()
        self.assertEqual(self.request('POST', '/api/folder', '[]')[0], 400)


if __name__ == '__main__':
    unittest.main()

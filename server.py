"""LAN Shelf: a dependency-free local network file server."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

BASE = Path(__file__).resolve().parent


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root, code):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.code = code
        self.sessions = {}
        self.login_attempts = {}
        self.lock = threading.Lock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def reply(self, status, data, content_type='application/json', headers=None):
        body = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        cookies = dict(part.strip().split('=', 1) for part in self.headers.get('Cookie', '').split(';') if '=' in part)
        with self.server.lock:
            return self.server.sessions.get(cookies.get('lan_session'), 0) > time.monotonic()

    def login_allowed(self):
        # Trust Cloudflare forwarding headers only from the local tunnel process.
        peer = self.client_address[0]
        if peer in ('127.0.0.1', '::1'):
            peer = self.headers.get('CF-Connecting-IP', peer)
        now = time.monotonic()
        with self.server.lock:
            self.server.login_attempts = {key: value for key, value in self.server.login_attempts.items() if now - value[0] < 60}
            started, count = self.server.login_attempts.get(peer, (now, 0))
            if count >= 10 or len(self.server.login_attempts) >= 10000:
                return False
            self.server.login_attempts[peer] = (started, count + 1)
        return True

    def path_for(self, relative):
        target = (self.server.root / relative).resolve()
        if not target.is_relative_to(self.server.root):
            raise ValueError('Path is outside the shared folder.')
        # Do not expose symbolic links or junctions from the shared directory.
        part = self.server.root
        for segment in target.relative_to(self.server.root).parts:
            part = part / segment
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise ValueError('Linked folders are not supported.')
        return target

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            if url.path == '/':
                return self.reply(200, (BASE / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/session':
                return self.reply(200, {'authenticated': self.authorized()})
            if not self.authorized():
                return self.reply(401, {'error': 'Enter the access code shown on the host computer.'})
            relative = parse_qs(url.query).get('path', [''])[0]
            target = self.path_for(relative)
            if url.path == '/api/files':
                entries = []
                for p in target.iterdir():
                    if p.name.startswith('.lan-upload-') or p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                        continue
                    stat = p.stat()
                    entries.append({'name': p.name, 'directory': p.is_dir(), 'size': stat.st_size, 'modified': stat.st_mtime})
                entries.sort(key=lambda e: (not e['directory'], e['name'].lower()))
                return self.reply(200, {'files': entries})
            if url.path == '/api/download' and target.is_file():
                with target.open('rb') as source:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(os.fstat(source.fileno()).st_size))
                    self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(target.name))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'private, no-store')
                    self.end_headers()
                    while chunk := source.read(1024 * 1024):
                        self.wfile.write(chunk)
                return
            if url.path == '/api/download' and target.is_dir():
                with tempfile.TemporaryFile() as archive:
                    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
                        for parent, directories, filenames in os.walk(target, followlinks=False):
                            parent = Path(parent)
                            directories[:] = [name for name in directories if not name.startswith('.lan-upload-') and not (parent / name).is_symlink() and not (hasattr(parent / name, 'is_junction') and (parent / name).is_junction())]
                            bundle.write(parent, (Path(target.name) / parent.relative_to(target)).as_posix() + '/')
                            for name in filenames:
                                entry = parent / name
                                if not name.startswith('.lan-upload-') and not entry.is_symlink() and entry.is_file():
                                    bundle.write(entry, (Path(target.name) / entry.relative_to(target)).as_posix())
                    length = archive.tell()
                    archive.seek(0)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(target.name + '.zip'))
                    self.send_header('Cache-Control', 'private, no-store')
                    self.end_headers()
                    while chunk := archive.read(1024 * 1024):
                        self.wfile.write(chunk)
                return
            self.reply(404, {'error': 'Not found.'})
        except (ValueError, OSError) as exc:
            self.reply(400, {'error': str(exc)})

    def do_POST(self):
        temporary = None
        try:
            # Custom header blocks cross-origin form submissions; no CORS is enabled.
            if self.headers.get('X-LAN-Shelf') != '1':
                return self.reply(403, {'error': 'Invalid request.'})
            url = urlsplit(self.path)
            length = int(self.headers.get('Content-Length', '-1'))
            if length < 0:
                return self.reply(411, {'error': 'Content-Length is required.'})
            if url.path == '/api/login':
                if not self.login_allowed():
                    return self.reply(429, {'error': 'Too many login attempts. Wait one minute and try again.'}, headers={'Retry-After': '60'})
                if length > 4096:
                    return self.reply(413, {'error': 'Request too large.'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object.')
                if not hmac.compare_digest(str(data.get('code', '')).encode(), self.server.code.encode()):
                    return self.reply(403, {'error': 'That access code is incorrect.'})
                token = secrets.token_urlsafe(32)
                with self.server.lock:
                    now = time.monotonic()
                    self.server.sessions = {key: expiry for key, expiry in self.server.sessions.items() if expiry > now}
                    if len(self.server.sessions) >= 1000:
                        del self.server.sessions[next(iter(self.server.sessions))]
                    self.server.sessions[token] = now + 12 * 3600
                secure = '; Secure' if self.client_address[0] in ('127.0.0.1', '::1') and self.headers.get('X-Forwarded-Proto') == 'https' else ''
                return self.reply(200, {'ok': True}, headers={'Set-Cookie': f'lan_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}'})
            if not self.authorized():
                return self.reply(401, {'error': 'Please sign in again.'})
            if url.path == '/api/folder':
                if length > 8192:
                    return self.reply(413, {'error': 'Request too large.'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object.')
                parent = self.path_for(data.get('path', ''))
                name = self.valid_name(data.get('name', ''))
                with self.server.lock:
                    destination = parent / name
                    if data.get('unique'):
                        index = 1
                        while destination.exists():
                            destination = parent / f'{name} ({index})'
                            index += 1
                    destination.mkdir()
                return self.reply(201, {'ok': True, 'name': destination.name})
            if url.path == '/api/upload':
                query = parse_qs(url.query)
                parent = self.path_for(query.get('path', [''])[0])
                name = self.valid_name(query.get('name', [''])[0])
                if not parent.is_dir():
                    raise ValueError('Destination folder does not exist.')
                with tempfile.NamedTemporaryFile(prefix='.lan-upload-', dir=parent, delete=False) as output:
                    temporary = Path(output.name)
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('Upload interrupted.')
                        output.write(chunk)
                        remaining -= len(chunk)
                with self.server.lock:
                    destination = parent / name
                    index = 1
                    while destination.exists():
                        destination = parent / f'{Path(name).stem} ({index}){Path(name).suffix}'
                        index += 1
                    # Hard-link creation is atomic and cannot overwrite an existing file.
                    os.link(temporary, destination)
                    temporary.unlink()
                    temporary = None
                return self.reply(201, {'name': destination.name})
            self.reply(404, {'error': 'Not found.'})
        except (ValueError, OSError) as exc:
            self.reply(400, {'error': str(exc)})
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def valid_name(name):
        if not isinstance(name, str) or not name or name in ('.', '..') or name.startswith('.lan-upload-') or any(c in name for c in '/\\<>:"|?*') or any(ord(c) < 32 for c in name) or name.endswith((' ', '.')):
            raise ValueError('Choose a valid file or folder name.')
        if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
            raise ValueError('This name is reserved by Windows.')
        return name


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def access_code():
    if os.environ.get('LAN_SHARE_CODE'):
        return os.environ['LAN_SHARE_CODE']
    filename = BASE / '.lan-access-code'
    try:
        with filename.open('x', encoding='utf-8') as output:
            output.write(secrets.token_hex(8))
        if os.name != 'nt':
            filename.chmod(0o600)
    except FileExistsError:
        pass
    code = filename.read_text(encoding='utf-8').strip()
    if not code:
        raise ValueError('The .lan-access-code file is empty.')
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Share files with browsers on your LAN.')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--folder', type=Path, default=BASE / 'shared')
    parser.add_argument('--background', action='store_true', help='Write output to server.log for automatic startup')
    args = parser.parse_args()
    if args.background:
        sys.stdout = sys.stderr = (BASE / 'server.log').open('a', encoding='utf-8', buffering=1)
    code = access_code()
    server = Server((args.host, args.port), args.folder, code)
    print(f'\n  LAN Shelf\n  This computer: http://localhost:{args.port}\n  Other devices: http://{lan_ip()}:{args.port}\n  Access code:   {code}\n  Shared folder: {server.root}\n\n  Keep this window open. Press Ctrl+C to stop.\n', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

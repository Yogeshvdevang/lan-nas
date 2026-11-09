"""Run an opt-in temporary Cloudflare HTTPS tunnel to the local file server."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

BASE = Path(__file__).resolve().parent


def main():
    local = BASE / 'tools' / ('cloudflared.exe' if os.name == 'nt' else 'cloudflared')
    executable = str(local) if local.is_file() else shutil.which('cloudflared')
    if not executable:
        raise SystemExit('Install cloudflared first: https://developers.cloudflare.com/tunnel/downloads/')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/session', timeout=5) as response:
            if response.status != 200:
                raise OSError('Server did not respond successfully.')
    except OSError:
        raise SystemExit('Start LAN Shelf on port 8000 first (start.bat or sh start.sh).')
    print('Starting temporary remote sharing. The link changes each time.\nAnyone with the link and your access code can browse, upload, and download.\nKeep this process running. Ctrl+C stops remote access.\n', flush=True)
    process = subprocess.Popen([executable, 'tunnel', '--url', 'http://127.0.0.1:8000', '--no-autoupdate'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    link_file = BASE / 'remote-url.txt'
    link = None
    try:
        for line in process.stdout:
            print(line.rstrip(), flush=True)
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if match:
                link = match.group()
                link_file.write_text(link + '\n', encoding='utf-8')
                print('\nSHARE THIS LINK: ' + link + '\n', flush=True)
        if process.wait():
            raise SystemExit('Tunnel stopped with an error. See the output above.')
    except KeyboardInterrupt:
        print('\nStopping remote sharing.', flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if link and link_file.exists() and link_file.read_text(encoding='utf-8').strip() == link:
            link_file.unlink()


if __name__ == '__main__':
    main()

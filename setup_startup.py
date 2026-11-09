"""Install/remove per-user login startup on Windows and Linux desktops."""
import argparse
import os
from pathlib import Path
import sys
from server import BASE, access_code


def windows_script(python, script, folder):
    # VBScript quotes and Windows command-line quotes are separate layers.
    import subprocess
    command = subprocess.list2cmdline([str(python), str(script), '--background', '--folder', str(folder)])
    return 'CreateObject("WScript.Shell").Run "' + command.replace('"', '""') + '", 0, False\n'


def desktop_quote(value):
    # Exec field quoting, then Desktop Entry string escaping.
    value = str(value).replace('%', '%%')
    value = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    return '"' + value.replace('\\', '\\\\') + '"'


def linux_entry(python, script, folder):
    command = ' '.join(desktop_quote(v) for v in [python, script, '--background', '--folder', folder])
    return '[Desktop Entry]\nType=Application\nName=LAN Shelf\nComment=Share files on your local network\nExec=' + command + '\nTerminal=false\nX-GNOME-Autostart-enabled=true\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove', action='store_true')
    parser.add_argument('--folder', type=Path, default=BASE / 'shared')
    args = parser.parse_args()
    if sys.platform == 'win32':
        target = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/LAN Shelf.vbs'
        python = Path(sys.executable).with_name('pythonw.exe')
        if not python.exists():
            parser.error('pythonw.exe is missing; install standard Python for Windows.')
        content = windows_script(python, BASE / 'server.py', args.folder.resolve())
        encoding = 'utf-16'
    elif sys.platform.startswith('linux'):
        target = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'autostart/lan-shelf.desktop'
        content = linux_entry(sys.executable, BASE / 'server.py', args.folder.resolve())
        encoding = 'utf-8'
    else:
        parser.error('Automatic startup supports Windows and Linux desktops.')
    if args.remove:
        target.unlink(missing_ok=True)
        print('Automatic startup removed. An already running server is not stopped.')
        return
    args.folder.resolve().mkdir(parents=True, exist_ok=True)
    code = access_code()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    print(f'Automatic startup installed: {target}\nStarts after you sign in, not before login.\nAccess code: {code}\nLogs: {BASE / "server.log"}\nKeep the project at: {BASE}\nTo start now, use start.bat (Windows) or sh start.sh (Linux).')


if __name__ == '__main__':
    main()

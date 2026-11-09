# LAN Shelf

A browser-based file shelf for devices on the same local network. Includes uploads, downloads, folders, search, transfer progress, and an access code. Uses Python 3.12+ with no dependencies.

## Start on Windows

1. Double-click **start.bat** (or run `python server.py`).
2. Open the **Other devices** address printed in the window on another computer or phone connected to the same Wi-Fi/LAN.
3. Enter the access code printed in that window.

If Windows asks about Python network access, allow **Private networks**. Keep the server window open. Press Ctrl+C to stop.

Files are stored in the `shared` folder next to the app. You can also put files directly in this folder. Uploads with existing names get a numbered suffix; incomplete transfers are cleaned up. Large uploads stream to disk rather than being held in memory. Everyone with the access code can read and add files.

## Options

Drop files or folders into the upload area, or use **Upload folder** to select an entire folder. Folder drag-and-drop also preserves empty subfolders in browsers that support directory entries. Its files and subfolders are copied into the current shared location. If the folder name already exists, a numbered copy is created. Browser folder selection includes files only, so empty subfolders are not uploaded. Use **Download ZIP** beside any shared folder to download it with its contents (including empty folders). ZIP downloads are prepared on the host before the transfer starts and need temporary disk space.

You can also copy whole folders directly into `shared` on the host computer; they appear in the browser automatically after refreshing.

```powershell
python server.py --port 8080
python server.py --folder "D:\My Shared Files"
# Optional override of the saved access code:
$env:LAN_SHARE_CODE = 'your-long-access-code'
python server.py
```

## Linux

Install Python 3.12+ using your distribution's package manager, copy this project to Linux (or open it on a mounted shared partition), and run:

```sh
sh start.sh
```

Open the LAN address printed by the server. The same browser interface works on Windows, Linux, and phones.

## Automatic startup on both systems

On Windows, double-click `enable-startup.bat`, or run `python setup_startup.py`.
On a Linux desktop, run `python3 setup_startup.py` once, as your normal user (not sudo).

These install per-user login startup: the server starts in the background when you **sign in** to that OS. They do not run before login. Linux needs a desktop environment supporting XDG autostart. The computer must remain awake. Keep the project in the same location after setup; rerun setup if you move it. Background output goes to `server.log`. The access code is saved in `.lan-access-code` so it stays the same after restarts. To change it, edit that file and restart the server. The environment variable above overrides it.

To disable startup, run `python setup_startup.py --remove` on Windows or `python3 setup_startup.py --remove` on Linux. This does not stop a currently running server.

For dual boot, install startup separately inside **each OS**. To see the same files in both, choose a data partition accessible to both systems and pass its OS-specific path when installing:

```powershell
python setup_startup.py --folder "D:\LAN-Shared"
```

```sh
python3 setup_startup.py --folder "/mnt/data/LAN-Shared"
```

Those paths are examples: they must refer to the same actual folder. Ensure the partition is mounted before Linux login. Use a filesystem that supports hard links (the uploader requires them), such as NTFS with a suitable Linux driver; exFAT/FAT are not supported. Shut Windows down fully before accessing its NTFS volumes from Linux; avoid a hibernated Windows volume. Separate project copies have separate access codes unless you copy `.lan-access-code` too. The LAN IP can differ between operating systems; check `server.log` after switching.

## Temporary internet sharing

Start the local server, then double-click `start-remote.bat` on Windows or run `sh start-remote.sh` on Linux. Windows includes a downloaded, checksum-verified cloudflared executable in `tools`; on Linux install cloudflared from https://developers.cloudflare.com/tunnel/downloads/ first.

The remote launcher prints an HTTPS address and saves it in `remote-url.txt`. Give that link and the access code to people who should be able to **browse, upload, download, and create folders**. All authenticated users have the same access. Files remain on this computer; traffic passes through Cloudflare. Sessions expire after 12 hours, and login requests are limited to 10 per minute per IP.

Keep the computer awake and both the server and tunnel running. Press Ctrl+C in the remote launcher to end remote access. Internet sharing is not added to automatic startup. After restarting the tunnel, share its new address. Cloudflare Quick Tunnels are intended for testing/temporary use and have no uptime guarantee: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

Cloudflare imposes upload request limits (100 MB on Free/Pro); this app sends one request per file, so use files under 100 MB remotely. LAN uploads bypass that limit. Slow transfers may also encounter proxy timeouts. For a permanent address, configure a named tunnel with your own domain.

This is a browser file-sharing app, not a Windows SMB mapped drive. LAN HTTP transfers are not encrypted; the remote link uses HTTPS. Do not forward port 8000 directly to the internet. If LAN devices cannot connect, check the Windows firewall, confirm they are on the same network, and disable Wi-Fi client isolation or guest-network isolation where appropriate. VPNs or multiple adapters can cause the printed IP to differ from your LAN address; use the host's Wi-Fi/Ethernet IPv4 address from `ipconfig` in that case.

## Verify

Run `python -m unittest -v`. Tests use an isolated temporary folder and loopback port.

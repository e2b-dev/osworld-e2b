import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { Template, waitForPort } from 'e2b'

// OSWorld-oriented Ubuntu 22.04 GNOME guest for E2B.
//
// This is a native reconstruction, not a bit-for-bit conversion of OSWorld's
// qcow2. It uses the same Ubuntu release, GNOME family, screen geometry, user,
// major applications, and OSWorld control interfaces. VS Code is pinned to the
// reference image's 1.91.1 via Microsoft's permanent versioned .deb URL.
// Chrome cannot be version-pinned the same way (Google's apt repo serves only
// the latest stable and does not archive old .debs), so it is apt-mark held:
// each immutable template build freezes whatever version it installed and the
// guest can never drift. Matching the qcow2's exact Chrome needs its version
// number plus an archived .deb source.

const filesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'files')

export const template = Template({ fileContextPath: filesDir })
  .fromImage('ubuntu:22.04')
  .setUser('root')
  .setWorkdir('/')
  .setEnvs({
    DEBIAN_FRONTEND: 'noninteractive',
    DEBIAN_PRIORITY: 'high',
    PIP_DISABLE_PIP_VERSION_CHECK: '1',
    PIP_NO_CACHE_DIR: '1',
    LANG: 'en_US.UTF-8',
    TZ: 'UTC',
  })
  .runCmd('apt-get update')
  // ---- desktop stack (GNOME) + software GL --------------------------------
  .aptInstall([
    'gnome-session',
    'gnome-shell',
    'gnome-terminal',
    'nautilus',
    'gnome-settings-daemon',
    'gnome-control-center',
    'gsettings-desktop-schemas',
    'dconf-cli',
    'accerciser',
    // themes + cursor (fixes mutter "No cursor theme available" + real rendering)
    'adwaita-icon-theme',
    'gnome-themes-extra',
    'dmz-cursor-theme',
    'libgl1-mesa-dri',
    'libglx-mesa0',
    'mesa-utils',
    'xvfb',
    'x11-utils',
    'x11-xserver-utils',
    // ---- session bus + accessibility --------------------------------------
    'dbus-x11',
    'dbus-user-session',
    'at-spi2-core',
    'python3-pyatspi',
    'python3-gi',
    'python3-tk',
    'python3-xlib',
    'python3-dev',
    'python3-pip',
    // ---- OSWorld evaluator/tooling binaries -------------------------------
    'gnome-screenshot',
    'scrot',
    'wmctrl',
    'xdotool',
    'xclip',
    'socat',
    'iproute2',
    'ffmpeg',
    // ---- office / productivity apps evaluators hard-reference -------------
    'libreoffice',
    'libreoffice-gnome',
    'gimp',
    'vlc',
    'thunderbird',
    // evince = the reference GNOME desktop's PDF handler. Without it xdg-open
    // resolves application/pdf to GIMP/LO Draw rather than a PDF viewer.
    'evince',
    // ---- fonts / locale ---------------------------------------------------
    'fonts-dejavu',
    'fonts-liberation',
    'fonts-noto',
    'fonts-noto-cjk',
    'locales',
    'tzdata',
    // ---- misc -------------------------------------------------------------
    'gnupg',
    'apt-transport-https',
    'curl',
    'ca-certificates',
    'sudo',
  ], { noInstallRecommends: false })
  // Locale
  .runCmd([
    'locale-gen en_US.UTF-8',
    'update-locale LANG=en_US.UTF-8',
    'ln -sf /usr/share/zoneinfo/UTC /etc/localtime',
  ])
  // ---- Chrome from Google's apt repo (evaluators assert `google-chrome`) ---
  .runCmd([
    'curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg',
    'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list',
    'apt-get update',
    'apt-get install -y google-chrome-stable',
    // Freeze the installed version inside the guest; the immutable template
    // build pins it across sandboxes.
    'apt-mark hold google-chrome-stable',
  ])
  // ---- VSCode pinned to the OSWorld reference image's 1.91.1 --------------
  // Installed from Microsoft's permanent versioned .deb URL, not the rolling
  // apt repo: 1.91.1 predates the Copilot chat panel and sign-in surfaces
  // that measurably distracted agents in live runs on newer builds.
  .runCmd([
    'curl -fsSL -o /tmp/code_1.91.1.deb "https://update.code.visualstudio.com/1.91.1/linux-deb-x64/stable"',
    'apt-get install -y /tmp/code_1.91.1.deb',
    'rm -f /tmp/code_1.91.1.deb',
    'apt-mark hold code',
  ])
  // ---- create OSWorld's uid-1000 `user` account ---------------------------
  .runCmd([
    'id user >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash user',
    'usermod -aG sudo,audio,video user || true',
    'echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-user',
    'echo "user:password" | chpasswd',
    'mkdir -p /home/user/.local/share/keyrings /home/user/.config/vlc',
    'touch /home/user/.local/share/keyrings/login.keyring /home/user/.Xauthority',
    // One Chrome profile, two views: the google-chrome shim launches with
    // --user-data-dir=google-chrome-cdp (Chrome >=136 disables the debug port
    // on the default path, even passed explicitly - probed on Chrome 150),
    // while OSWorld's profile getters hardcode ~/.config/google-chrome/... .
    // Symlinking the default path onto the CDP dir keeps both consistent.
    'mkdir -p /home/user/.config/google-chrome-cdp',
    'ln -sfn google-chrome-cdp /home/user/.config/google-chrome',
  ])
  // ---- Chrome: use the compatibility wrapper on every GUI launch path -----
  .runCmd([
    "sed -Ei '/^Exec=/ s#/usr/bin/google-chrome-stable#/usr/local/bin/google-chrome#g; /^Exec=/ s#google-chrome-stable#/usr/local/bin/google-chrome#g' /usr/share/applications/google-chrome.desktop || true",
  ])
  // ---- PATH shims: make task-config CDP launches work through ingress -----
  // Task configs run `google-chrome --remote-debugging-port=1337` + a socat
  // 9222->1337 forward. The chrome shim adds the flags Chrome >=136 needs to
  // actually open the debug port; the socat shim swaps the plain TCP forward
  // for cdp_hostfix.py (Host-normalizing proxy), since E2B's ingress rewrites
  // the Host header and Chrome's DevTools host check rejects it.
  .copy('google-chrome-shim.sh', '/usr/local/bin/google-chrome', { mode: 0o755 })
  .copy('socat-shim.sh', '/usr/local/bin/socat', { mode: 0o755 })
  // Keep the Host-normalizing CDP listener present even after GUI relaunches.
  .runCmd("printf '[Unit]\\nDescription=OSWorld CDP host-normalizing proxy\\nAfter=network.target\\n[Service]\\nUser=user\\nExecStart=/usr/bin/python3 /opt/osworld-server/cdp_hostfix.py\\nRestart=always\\n[Install]\\nWantedBy=multi-user.target\\n' > /etc/systemd/system/osworld-cdp.service")
  // ---- VLC Lua HTTP interface :8080 (baked; matches full install) ---------
  .runCmd(
    "printf '[core]\\nextraintf=http\\n[lua]\\nhttp-port=8080\\nhttp-host=0.0.0.0\\nhttp-password=password\\n[qt]\\nqt-privacy-ask=0\\nqt-updates-notif=0\\n' > /home/user/.config/vlc/vlcrc",
  )
  // Avoid first-run UI that intercepts benchmark actions. These values use
  // LibreOffice's own registry paths from the installed 7.3.7 schema.
  .makeDir('/home/user/.config/libreoffice/4/user')
  .copy(
    'libreoffice-registrymodifications.xcu',
    '/home/user/.config/libreoffice/4/user/registrymodifications.xcu',
  )
  // ---- system-wide dconf defaults: a11y + interface + DPI/scaling ---------
  // Matches the OSWorld reference GNOME session: toolkit-accessibility on (so
  // GTK/Qt apps expose AT-SPI trees), Adwaita cursor/theme, 1.0 text scaling
  // and 96 DPI to pair with the baked 1920x1080 framebuffer.
  .makeDir('/etc/dconf/db/site.d')
  .makeDir('/etc/dconf/profile')
  .copy('dconf-osworld', '/etc/dconf/db/site.d/00-osworld')
  .runCmd([
    "printf 'user-db:user\\nsystem-db:site\\n' > /etc/dconf/profile/user",
    'dconf update || true',
    // 96 DPI via Xresources so Xft-based apps size text consistently at 1080p.
    "printf 'Xft.dpi: 96\\n' > /home/user/.Xresources",
  ])
  // ---- OSWorld server payload + session scripts ---------------------------
  .makeDir('/opt/osworld-server')
  .copy('server', '/opt/osworld-server')
  .copy('session_inner.sh', '/opt/osworld-server/session_inner.sh', { mode: 0o755 })
  .copy('start.sh', '/opt/osworld-server/start.sh', { mode: 0o755 })
  .runCmd('python3 -m pip install --no-cache-dir -r /opt/osworld-server/requirements.txt')
  .runCmd([
    'ln -sf /usr/bin/python3 /usr/bin/python || true',
    'chown -R user:user /opt/osworld-server /home/user',
    'systemctl enable --now osworld-cdp.service',
  ])
  // Boot GNOME + server inside a logind session (start.sh runs as root).
  .setStartCmd('bash /opt/osworld-server/start.sh', waitForPort(5000))

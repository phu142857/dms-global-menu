# DMS Global Menu

A macOS-style application menu widget for Dux Modular Shell (DMS) on Niri.
It implements the standard `com.canonical.AppMenu.Registrar` protocol, follows
Niri's focused window, and activates real application menu actions.

The interface uses English labels throughout, compact macOS-like menu density,
bold active-application typography, and standard Window/Space terminology.
Menu popouts are headerless, matching macOS by opening directly on commands.
Each popout is anchored to the exact top-level menu that opened it, and moves
in place when switching between menus while it remains open.
Layer-shell popouts preserve the last real application focus, preventing an
open menu from switching to the Desktop fallback.

## Requirements

- DMS 2.0 or newer
- Niri
- Python 3 with `dbus-python` and PyGObject
- `libdbusmenu` and an application-side exporter such as `appmenu-gtk-module`

On Arch Linux:

```sh
sudo pacman -S python-dbus python-gobject libdbusmenu-glib appmenu-gtk-module
```

Set these variables before starting applications:

```sh
export GTK_MODULES=appmenu-gtk-module
export UBUNTU_MENUPROXY=1
```

## Install

```sh
git clone https://github.com/phu142857/dms-global-menu.git \
  ~/.config/dms/plugins/globalMenu
dms ipc call plugins reload globalMenu
```

Then add **Global Menu** to the left section of the DMS bar. Applications must
be restarted after the registrar starts before their menus can be exported.

## Compatibility

The backend supports both Canonical `com.canonical.dbusmenu` registrations and
native Wayland `org.gtk.Menus`/`org.gtk.Actions` exports from
`appmenu-gtk-module`. GTK 3 applications work without relying on an X11 window
ID. Applications that do not export either D-Bus protocol keep their in-window
menu and receive a safe fallback with Niri window and workspace actions. The
plugin never borrows another application's menu or invents unavailable
application actions.

This gives every focused window a useful menu while preserving native menus
where applications expose them. A true application menu still requires an API
from the application or its toolkit.

### Code - OSS and Cursor

Electron does not export its application menu through the Linux D-Bus menu
protocols when running natively on Wayland. Install the bundled companion
extension to expose menu commands over a local Unix socket:

```sh
code-oss --install-extension \
  ~/.config/dms/plugins/globalMenu/dist/dms-global-menu-bridge-1.1.0.vsix --force
cursor --install-extension \
  ~/.config/dms/plugins/globalMenu/dist/dms-global-menu-bridge-1.1.0.vsix --force
```

Reload the editor window after installation. The bridge has no network access,
does not collect telemetry, and does not read editor contents.

### Zen Browser

Zen/Firefox on native Wayland currently exports neither a D-Bus application
menu nor a sufficiently labelled browser-chrome accessibility tree. The plugin
therefore provides the universal Window/Workspace fallback instead of
presenting broken or mislabelled browser actions. Native tab/history actions
would require a signed Firefox WebExtension and a native-messaging bridge.

## License

MIT

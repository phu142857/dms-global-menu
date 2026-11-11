# DMS Global Menu

A macOS-style application menu widget for Dux Modular Shell (DMS) on Niri.
It implements the standard `com.canonical.AppMenu.Registrar` protocol, follows
Niri's focused window, and activates real application menu actions.

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
menu; the widget shows only the application name and never borrows another
application's menu.

## License

MIT

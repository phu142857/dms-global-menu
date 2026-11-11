#!/usr/bin/env python3
"""DMS Global Menu backend.

Owns Canonical's AppMenu registrar, follows Niri focus, and publishes a small
JSON model for the QML widget. No DMS-private API is used here.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib


REGISTRAR_NAME = "com.canonical.AppMenu.Registrar"
REGISTRAR_PATH = "/com/canonical/AppMenu/Registrar"
DBUSMENU_IFACE = "com.canonical.dbusmenu"
CONTROL_NAME = "io.github.phu142857.DmsGlobalMenu"
CONTROL_PATH = "/io/github/phu142857/DmsGlobalMenu"
STATE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "dms/global-menu/state.json"
LOG_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "dms/global-menu.log"


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, dbus.Array, dbus.Struct)):
        return [plain(item) for item in value]
    if isinstance(value, (dbus.Boolean, bool)):
        return bool(value)
    if isinstance(value, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, int)):
        return int(value)
    if isinstance(value, (dbus.Double, float)):
        return float(value)
    if isinstance(value, (dbus.String, dbus.ObjectPath, str)):
        return str(value)
    if isinstance(value, dbus.ByteArray):
        return ""
    return str(value)


def clean_label(label: Any) -> str:
    text = str(label or "")
    # D-Bus menu mnemonics use underscores; escaped underscores are retained.
    marker = "\0"
    return text.replace("__", marker).replace("_", "").replace(marker, "_").strip()


def friendly_app_name(app_id: str, title: str) -> str:
    known = {
        "code-oss": "Code - OSS",
        "code": "Visual Studio Code",
        "zen": "Zen Browser",
        "kitty": "Kitty",
        "org.gnome.nautilus": "Files",
    }
    if app_id in known:
        return known[app_id]
    tail = app_id.rsplit(".", 1)[-1].replace("-", " ").replace("_", " ").strip()
    if tail:
        return tail.title()
    return title.split(" — ", 1)[-1].strip() or "Desktop"


@dataclass
class Registration:
    window_id: int
    sender: str
    path: str
    pid: int


class MenuBackend:
    def __init__(self, bus: dbus.SessionBus):
        self.bus = bus
        self.registrations: dict[int, Registration] = {}
        self.focus: dict[str, Any] = {}
        self.active: Registration | None = None
        self.active_kind = ""
        self.active_interface: Any = None
        self.active_actions: Any = None
        self.gtk_groups: set[int] = set()
        self.signal_matches: list[Any] = []
        self.tokens: dict[str, Any] = {}
        self.revision = 0
        self._refresh_source = 0
        self._event_process: subprocess.Popen[str] | None = None
        self.write_state("starting", [])

    def connection_pid(self, sender: str) -> int:
        try:
            daemon = dbus.Interface(self.bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
            return int(daemon.GetConnectionUnixProcessID(sender))
        except dbus.DBusException:
            return 0

    def register(self, window_id: int, path: str, sender: str) -> None:
        registration = Registration(int(window_id), str(sender), str(path), self.connection_pid(str(sender)))
        self.registrations[registration.window_id] = registration
        log(f"registered window={registration.window_id} sender={registration.sender} pid={registration.pid} path={registration.path}")
        self.choose_active()

    def unregister(self, window_id: int) -> None:
        self.registrations.pop(int(window_id), None)
        self.choose_active()

    def remove_sender(self, sender: str) -> None:
        dead = [window_id for window_id, item in self.registrations.items() if item.sender == sender]
        for window_id in dead:
            self.registrations.pop(window_id, None)
        if dead:
            self.choose_active()

    def set_focus(self, window: dict[str, Any] | None) -> None:
        self.focus = window or {}
        self.choose_active()

    def choose_active(self) -> None:
        focus_pid = int(self.focus.get("pid") or 0)
        candidates = [item for item in self.registrations.values() if item.pid == focus_pid and focus_pid]
        selected = candidates[-1] if candidates else None
        # Some applications register from a helper process. If exactly one menu
        # exists it is safer to show it than a stale menu from another app.
        if selected is None and len(self.registrations) == 1:
            only = next(iter(self.registrations.values()))
            if self._same_process_tree(focus_pid, only.pid):
                selected = only
        selected_kind = "dbusmenu" if selected is not None else ""
        if selected is None:
            selected = self.discover_gtk_menu(focus_pid)
            selected_kind = "gtk" if selected is not None else ""
        if selected is None and str(self.focus.get("app_id") or "") in {"code", "code-oss", "cursor"}:
            selected = self.discover_vscode_bridge(focus_pid)
            selected_kind = "vscode" if selected is not None else ""
        if selected != self.active or selected_kind != self.active_kind:
            self._detach_menu()
            self.active = selected
            self.active_kind = selected_kind
            self._attach_menu()
        self.refresh()

    @staticmethod
    def discover_vscode_bridge(focus_pid: int) -> Registration | None:
        if not focus_pid:
            return None
        runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        bridge = runtime_dir / f"dms-global-menu-vscode-{focus_pid}.sock"
        if bridge.is_socket():
            return Registration(-1000, "vscode", str(bridge), focus_pid)
        return None

    def discover_gtk_menu(self, focus_pid: int) -> Registration | None:
        """Find appmenu-gtk-module's native Wayland export for a process."""
        if not focus_pid:
            return None
        try:
            daemon = dbus.Interface(self.bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
            names = daemon.ListNames()
        except dbus.DBusException:
            return None
        for sender in names:
            sender = str(sender)
            if not sender.startswith(":") or self.connection_pid(sender) != focus_pid:
                continue
            for index in range(16):
                path = f"/org/appmenu/gtk/window/menus/menubar/{index}"
                try:
                    obj = self.bus.get_object(sender, path)
                    menu = dbus.Interface(obj, "org.gtk.Menus")
                    menu.Start(dbus.Array([0], signature="u"), timeout=1)
                    try:
                        menu.End(dbus.Array([0], signature="u"), timeout=1)
                    except dbus.DBusException:
                        pass
                    return Registration(-1 - index, sender, path, focus_pid)
                except dbus.DBusException:
                    continue
        return None

    @staticmethod
    def _parent_pid(pid: int) -> int:
        try:
            return int(Path(f"/proc/{pid}/stat").read_text().split()[3])
        except (OSError, ValueError, IndexError):
            return 0

    def _same_process_tree(self, first: int, second: int) -> bool:
        if not first or not second:
            return False
        left: set[int] = set()
        current = first
        for _ in range(8):
            if not current:
                break
            left.add(current)
            current = self._parent_pid(current)
        current = second
        for _ in range(8):
            if not current:
                break
            if current in left:
                return True
            current = self._parent_pid(current)
        return False

    def _detach_menu(self) -> None:
        for match in self.signal_matches:
            try:
                match.remove()
            except Exception:
                pass
        self.signal_matches.clear()
        if self.active_kind == "gtk" and self.active_interface is not None and self.gtk_groups:
            try:
                self.active_interface.End(dbus.Array(sorted(self.gtk_groups), signature="u"), timeout=1)
            except dbus.DBusException:
                pass
        self.active_interface = None
        self.active_actions = None
        self.gtk_groups.clear()
        self.tokens.clear()

    def _attach_menu(self) -> None:
        if self.active is None:
            return
        if self.active_kind == "vscode":
            return
        try:
            obj = self.bus.get_object(self.active.sender, self.active.path)
            if self.active_kind == "gtk":
                self.active_interface = dbus.Interface(obj, "org.gtk.Menus")
                self.active_actions = dbus.Interface(obj, "org.gtk.Actions")
                self.signal_matches.append(self.active_interface.connect_to_signal("Changed", self.schedule_refresh))
                self.signal_matches.append(self.active_actions.connect_to_signal("Changed", self.schedule_refresh))
            else:
                self.active_interface = dbus.Interface(obj, DBUSMENU_IFACE)
                self.signal_matches.append(self.active_interface.connect_to_signal("LayoutUpdated", self.schedule_refresh))
                self.signal_matches.append(self.active_interface.connect_to_signal("ItemsPropertiesUpdated", self.schedule_refresh))
        except dbus.DBusException as error:
            log(f"cannot attach menu: {error}")
            self.active_interface = None

    def schedule_refresh(self, *args: Any) -> None:
        if not self._refresh_source:
            self._refresh_source = GLib.timeout_add(100, self._scheduled_refresh)

    def _scheduled_refresh(self) -> bool:
        self._refresh_source = 0
        self.refresh()
        return False

    def refresh(self) -> None:
        if self.active_kind == "vscode" and self.active is not None:
            self.revision += 1
            self.tokens.clear()
            self.write_state("ready", self.read_vscode_menu())
            return
        if self.active_interface is None:
            self.tokens.clear()
            self.write_state("unsupported", [])
            return
        try:
            self.revision += 1
            self.tokens.clear()
            if self.active_kind == "gtk":
                menus = self.read_gtk_menu()
            else:
                _revision, layout = self.active_interface.GetLayout(0, -1, dbus.Array([], signature="s"), timeout=2)
                root = self.parse_item(layout)
                menus = [item for item in root.get("children", []) if item.get("visible", True) and not item.get("separator")]
            self.write_state("ready" if menus else "unsupported", menus)
        except dbus.DBusException as error:
            log(f"GetLayout failed: {error}")
            self.write_state("error", [])

    def read_vscode_menu(self) -> list[dict[str, Any]]:
        definitions = [
            ("File", [
                ("New Text File", "workbench.action.files.newUntitledFile"),
                ("Open File…", "workbench.action.files.openFile"),
                ("Open Folder…", "workbench.action.files.openFolder"),
                ("Save", "workbench.action.files.save"),
                ("Save As…", "workbench.action.files.saveAs"),
                ("Close Editor", "workbench.action.closeActiveEditor"),
            ]),
            ("Edit", [
                ("Undo", "undo"), ("Redo", "redo"),
                ("Cut", "editor.action.clipboardCutAction"),
                ("Copy", "editor.action.clipboardCopyAction"),
                ("Paste", "editor.action.clipboardPasteAction"),
                ("Find", "actions.find"),
                ("Replace", "editor.action.startFindReplaceAction"),
            ]),
            ("Selection", [
                ("Select All", "editor.action.selectAll"),
                ("Expand Selection", "editor.action.smartSelect.expand"),
                ("Shrink Selection", "editor.action.smartSelect.shrink"),
                ("Copy Line Up", "editor.action.copyLinesUpAction"),
                ("Copy Line Down", "editor.action.copyLinesDownAction"),
            ]),
            ("View", [
                ("Command Palette…", "workbench.action.showCommands"),
                ("Explorer", "workbench.view.explorer"),
                ("Search", "workbench.view.search"),
                ("Extensions", "workbench.view.extensions"),
                ("Toggle Primary Side Bar", "workbench.action.toggleSidebarVisibility"),
                ("Toggle Panel", "workbench.action.togglePanel"),
            ]),
            ("Go", [
                ("Back", "workbench.action.navigateBack"),
                ("Forward", "workbench.action.navigateForward"),
                ("Go to File…", "workbench.action.quickOpen"),
                ("Go to Symbol…", "workbench.action.gotoSymbol"),
                ("Go to Line…", "workbench.action.gotoLine"),
            ]),
            ("Run", [
                ("Start Debugging", "workbench.action.debug.start"),
                ("Run Without Debugging", "workbench.action.debug.run"),
                ("Stop Debugging", "workbench.action.debug.stop"),
                ("Restart Debugging", "workbench.action.debug.restart"),
            ]),
            ("Terminal", [
                ("New Terminal", "workbench.action.terminal.new"),
                ("Split Terminal", "workbench.action.terminal.split"),
                ("Kill Terminal", "workbench.action.terminal.kill"),
                ("Toggle Terminal", "workbench.action.terminal.toggleTerminal"),
            ]),
            ("Help", [
                ("Welcome", "workbench.action.openWalkthrough"),
                ("Show All Commands", "workbench.action.showCommands"),
                ("Keyboard Shortcuts", "workbench.action.openGlobalKeybindings"),
                ("About", "workbench.action.showAboutDialog"),
            ]),
        ]

        def item(label: str, command: str) -> dict[str, Any]:
            token = f"{self.revision}:vscode:{len(self.tokens)}"
            self.tokens[token] = command
            return {"label": label, "enabled": True, "visible": True,
                    "separator": False, "toggle_state": False,
                    "toggle_type": "", "token": token, "children": []}

        return [
            {"label": label, "enabled": True, "visible": True,
             "separator": False, "toggle_state": False, "toggle_type": "",
             "token": "", "children": [item(child_label, command) for child_label, command in children]}
            for label, children in definitions
        ]

    def parse_item(self, raw: Any) -> dict[str, Any]:
        item_id = int(raw[0])
        props = plain(raw[1])
        token = f"{self.revision}:{item_id}"
        self.tokens[token] = item_id
        item = {
            "label": clean_label(props.get("label", "")),
            "enabled": bool(props.get("enabled", True)),
            "visible": bool(props.get("visible", True)),
            "separator": props.get("type", "") == "separator",
            "toggle_state": int(props.get("toggle-state", 0)) == 1,
            "toggle_type": str(props.get("toggle-type", "")),
            "token": token,
            "children": [],
        }
        item["children"] = [self.parse_item(child) for child in raw[2]]
        return item

    def read_gtk_menu(self) -> list[dict[str, Any]]:
        menus: dict[tuple[int, int], list[Any]] = {}
        groups: set[int] = set()
        pending = {0}
        while pending:
            request = sorted(pending - groups)
            if not request:
                break
            groups.update(request)
            result = self.active_interface.Start(dbus.Array(request, signature="u"), timeout=2)
            for group, menu_id, items in result:
                menus[(int(group), int(menu_id))] = list(items)
            linked: set[int] = set()
            for items in menus.values():
                for raw in items:
                    for key in (":section", ":submenu"):
                        if key in raw:
                            linked.add(int(raw[key][0]))
            pending = linked
        stale = self.gtk_groups - groups
        if stale:
            self.active_interface.End(dbus.Array(sorted(stale), signature="u"), timeout=1)
        self.gtk_groups = groups

        descriptions = dict(self.active_actions.DescribeAll(timeout=2)) if self.active_actions is not None else {}

        def collect(link: tuple[int, int]) -> list[dict[str, Any]]:
            output: list[dict[str, Any]] = []
            for raw_props in menus.get(link, []):
                props = dict(raw_props)
                if ":section" in props:
                    section = props[":section"]
                    output.extend(collect((int(section[0]), int(section[1]))))
                    continue
                action = str(props.get("action", ""))
                action_name = action.split(".", 1)[1] if "." in action else action
                description = descriptions.get(action_name)
                enabled = bool(description[0]) if description is not None else True
                state = list(description[2]) if description is not None else []
                target = props.get("target")
                toggle_state = False
                if target is not None and state:
                    toggle_state = state[0] == target
                elif state and isinstance(state[0], (bool, dbus.Boolean)):
                    toggle_state = bool(state[0])
                token = f"{self.revision}:gtk:{len(self.tokens)}"
                if action_name:
                    self.tokens[token] = (action_name, target)
                children: list[dict[str, Any]] = []
                if ":submenu" in props:
                    submenu = props[":submenu"]
                    children = collect((int(submenu[0]), int(submenu[1])))
                is_separator = not props.get("label") and not action and not children
                output.append({
                    "label": clean_label(props.get("label", "")),
                    "enabled": enabled,
                    "visible": True,
                    "separator": is_separator,
                    "toggle_state": toggle_state,
                    "toggle_type": "radio" if target is not None else ("checkmark" if state else ""),
                    "token": token if action_name else "",
                    "children": children,
                })
            return output

        return [item for item in collect((0, 0)) if item.get("visible", True) and not item.get("separator")]

    def activate(self, token: str) -> bool:
        action = self.tokens.get(token)
        if action is None:
            return False
        if self.active_kind == "vscode" and self.active is not None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(2)
                    connection.connect(self.active.path)
                    connection.sendall((json.dumps({"command": action}) + "\n").encode("utf-8"))
                    response = json.loads(connection.makefile("r", encoding="utf-8").readline())
                return bool(response.get("ok"))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                log(f"VS Code bridge activation failed command={action}: {error}")
                return False
        if self.active_interface is None:
            return False
        try:
            if self.active_kind == "gtk":
                action_name, target = action
                parameters = dbus.Array([] if target is None else [target], signature="v")
                self.active_actions.Activate(action_name, parameters, dbus.Dictionary({}, signature="sv"), timeout=2)
            else:
                self.active_interface.Event(action, "clicked", dbus.Int32(0), dbus.UInt32(int(time.time())), timeout=2)
            self.schedule_refresh()
            return True
        except dbus.DBusException as error:
            log(f"activation failed token={token}: {error}")
            return False

    def write_state(self, status: str, menus: list[dict[str, Any]]) -> None:
        app_id = str(self.focus.get("app_id") or "")
        title = str(self.focus.get("title") or "")
        state = {
            "schema": 1,
            "app_id": app_id,
            "app_name": friendly_app_name(app_id, title),
            "window_title": title,
            "status": status,
            "menus": menus,
            "updated_at": int(time.time()),
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".global-menu-", dir=STATE_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            os.replace(temporary, STATE_PATH)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def query_focus(self) -> None:
        try:
            result = subprocess.run(
                ["niri", "msg", "--json", "focused-window"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            self.set_focus(json.loads(result.stdout))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            self.set_focus(None)

    def start_niri_watcher(self) -> None:
        def watch() -> None:
            while True:
                try:
                    self._event_process = subprocess.Popen(
                        ["niri", "msg", "--json", "event-stream"],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=1,
                    )
                    assert self._event_process.stdout is not None
                    for _line in self._event_process.stdout:
                        GLib.idle_add(self.query_focus)
                    self._event_process.wait()
                except OSError as error:
                    log(f"niri event stream failed: {error}")
                time.sleep(1)

        self.query_focus()
        threading.Thread(target=watch, name="niri-global-menu", daemon=True).start()


class Registrar(dbus.service.Object):
    def __init__(self, bus_name: dbus.service.BusName, backend: MenuBackend):
        self.backend = backend
        super().__init__(bus_name, REGISTRAR_PATH)

    @dbus.service.method(REGISTRAR_NAME, in_signature="uo", sender_keyword="sender")
    def RegisterWindow(self, window_id: int, menu_path: str, sender: str | None = None) -> None:
        assert sender is not None
        self.backend.register(int(window_id), str(menu_path), str(sender))
        registration = self.backend.registrations[int(window_id)]
        self.WindowRegistered(dbus.UInt32(window_id), registration.sender, dbus.ObjectPath(menu_path))

    @dbus.service.method(REGISTRAR_NAME, in_signature="u")
    def UnregisterWindow(self, window_id: int) -> None:
        self.backend.unregister(int(window_id))
        self.WindowUnregistered(dbus.UInt32(window_id))

    @dbus.service.method(REGISTRAR_NAME, in_signature="u", out_signature="so")
    def GetMenuForWindow(self, window_id: int) -> tuple[str, dbus.ObjectPath]:
        item = self.backend.registrations.get(int(window_id))
        if item is None:
            return "", dbus.ObjectPath("/")
        return item.sender, dbus.ObjectPath(item.path)

    @dbus.service.method(REGISTRAR_NAME, out_signature="a{u(so)}")
    def GetMenus(self) -> dict[dbus.UInt32, tuple[str, dbus.ObjectPath]]:
        return {
            dbus.UInt32(window_id): (item.sender, dbus.ObjectPath(item.path))
            for window_id, item in self.backend.registrations.items()
        }

    @dbus.service.signal(REGISTRAR_NAME, signature="uso")
    def WindowRegistered(self, window_id: dbus.UInt32, service: str, path: dbus.ObjectPath) -> None:
        pass

    @dbus.service.signal(REGISTRAR_NAME, signature="u")
    def WindowUnregistered(self, window_id: dbus.UInt32) -> None:
        pass


class Control(dbus.service.Object):
    def __init__(self, bus_name: dbus.service.BusName, backend: MenuBackend):
        self.backend = backend
        super().__init__(bus_name, CONTROL_PATH)

    @dbus.service.method(CONTROL_NAME, in_signature="s", out_signature="b")
    def Activate(self, token: str) -> bool:
        return self.backend.activate(str(token))

    @dbus.service.method(CONTROL_NAME)
    def Refresh(self) -> None:
        self.backend.refresh()

    @dbus.service.method(CONTROL_NAME)
    def Quit(self) -> None:
        os.kill(os.getpid(), signal.SIGTERM)


def call_control(method: str, *args: str) -> int:
    try:
        bus = dbus.SessionBus()
        interface = dbus.Interface(bus.get_object(CONTROL_NAME, CONTROL_PATH), CONTROL_NAME)
        if method == "activate":
            return 0 if bool(interface.Activate(args[0], timeout=2)) else 1
        interface.Refresh(timeout=2)
        return 0
    except (dbus.DBusException, IndexError) as error:
        log(f"control call failed: {error}")
        return 1


def run_daemon() -> int:
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    if bus.name_has_owner(CONTROL_NAME):
        return 0
    try:
        registrar_name = dbus.service.BusName(REGISTRAR_NAME, bus=bus, do_not_queue=True)
        control_name = dbus.service.BusName(CONTROL_NAME, bus=bus, do_not_queue=True)
    except dbus.DBusException as error:
        log(f"cannot own D-Bus names: {error}")
        return 1

    backend = MenuBackend(bus)
    Registrar(registrar_name, backend)
    Control(control_name, backend)

    bus.add_signal_receiver(
        lambda name, old, new: backend.remove_sender(str(name)) if old and not new else None,
        signal_name="NameOwnerChanged",
        dbus_interface="org.freedesktop.DBus",
        bus_name="org.freedesktop.DBus",
        path="/org/freedesktop/DBus",
    )
    backend.start_niri_watcher()
    loop = GLib.MainLoop()
    signal.signal(signal.SIGTERM, lambda *_: loop.quit())
    signal.signal(signal.SIGINT, lambda *_: loop.quit())
    log("daemon started")
    loop.run()
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "daemon"
    if command == "daemon":
        return run_daemon()
    if command == "activate":
        return call_control("activate", *sys.argv[2:])
    if command == "refresh":
        return call_control("refresh")
    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

import QtCore
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.DCommon.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root

    layerNamespacePlugin: "global-menu"

    property var menuState: ({
        "app_name": "Desktop",
        "status": "starting",
        "menus": []
    })
    property int selectedMenu: 0
    property var navigation: []
    property string backendPath: decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace("file://", ""))
    property string statePath: StandardPaths.writableLocation(StandardPaths.GenericCacheLocation) + "/dms/global-menu/state.json"
    readonly property var topMenus: menuState.menus || []
    readonly property var selectedTopMenu: topMenus.length > selectedMenu ? topMenus[selectedMenu] : ({ "children": [] })
    readonly property var visibleItems: {
        var node = selectedTopMenu;
        for (var i = 0; i < navigation.length; i++) {
            var children = node.children || [];
            if (navigation[i] < 0 || navigation[i] >= children.length)
                break;
            node = children[navigation[i]];
        }
        return node.children || [];
    }

    function runBackend(args) {
        var command = ["python3", backendPath];
        for (var i = 0; i < args.length; i++)
            command.push(String(args[i]));
        Quickshell.execDetached(command);
    }

    function openMenu(index) {
        selectedMenu = index;
        navigation = [];
        triggerPopout();
    }

    function activate(item) {
        if (!item || item.enabled === false || !item.token)
            return;
        runBackend(["activate", item.token]);
        closePopout();
    }

    Component.onCompleted: {
        runBackend(["daemon"]);
        reloadTimer.start();
    }

    FileView {
        id: stateFile
        path: root.statePath
        blockLoading: false
        watchChanges: true

        function parseState() {
            try {
                var parsed = JSON.parse(stateFile.text());
                root.menuState = parsed;
                if (root.selectedMenu >= root.topMenus.length)
                    root.selectedMenu = 0;
            } catch (error) {
                // The daemon atomically replaces this file. A short-lived read
                // failure is retried by reloadTimer without disturbing the bar.
            }
        }

        onLoaded: parseState()
        onFileChanged: reload()
        onLoadFailed: error => reloadTimer.start()
    }

    Timer {
        id: reloadTimer
        interval: 500
        repeat: true
        running: true
        onTriggered: stateFile.reload()
    }

    horizontalBarPill: Component {
        Row {
            id: menuRow
            height: root.widgetThickness
            spacing: 0

            Item {
                height: parent.height
                width: appLabel.implicitWidth + Theme.spacingM * 2

                StyledText {
                    id: appLabel
                    anchors.centerIn: parent
                    text: root.menuState.app_name || "Desktop"
                    color: Theme.surfaceText
                    font.pixelSize: root.textSize
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, 180)
                }
            }

            Repeater {
                model: root.topMenus

                delegate: Item {
                    required property var modelData
                    required property int index
                    height: menuRow.height
                    width: menuLabel.implicitWidth + Theme.spacingM * 2

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.cornerRadius
                        color: menuMouse.containsMouse || root.selectedMenu === index && root.interactionActive
                               ? Theme.chipSurface : "transparent"
                    }

                    StyledText {
                        id: menuLabel
                        anchors.centerIn: parent
                        text: modelData.label || ""
                        color: Theme.surfaceText
                        font.pixelSize: root.textSize
                    }

                    MouseArea {
                        id: menuMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openMenu(index)
                    }
                }
            }
        }
    }

    verticalBarPill: Component {
        DIcon {
            name: "menu"
            color: Theme.surfaceText
            size: root.iconSize
        }
    }

    popoutContent: Component {
        PopoutComponent {
            id: menuPopout
            headerText: root.navigation.length > 0
                        ? (root.selectedTopMenu.label || "Menu")
                        : (root.menuState.app_name || "Global Menu")
            detailsText: root.menuState.status === "ready"
                         ? (root.selectedTopMenu.label || "Application menu")
                         : "Ứng dụng này chưa xuất menu D-Bus"

            Column {
                width: parent.width
                spacing: 2

                Rectangle {
                    visible: root.navigation.length > 0
                    width: parent.width
                    height: visible ? 38 : 0
                    radius: Theme.cornerRadius
                    color: backMouse.containsMouse ? Theme.chipSurface : "transparent"

                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.spacingS

                        DIcon {
                            name: "arrow_back"
                            size: Theme.fontSizeLarge
                            color: Theme.surfaceText
                        }

                        StyledText {
                            text: "Quay lại"
                            color: Theme.surfaceText
                            font.pixelSize: Theme.fontSizeMedium
                        }
                    }

                    MouseArea {
                        id: backMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.navigation = root.navigation.slice(0, -1)
                    }
                }

                Repeater {
                    model: root.visibleItems

                    delegate: Item {
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: modelData.separator ? 9 : 38
                        visible: modelData.visible !== false

                        Rectangle {
                            visible: modelData.separator === true
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width
                            height: 1
                            color: Theme.outline
                            opacity: 0.45
                        }

                        Rectangle {
                            visible: modelData.separator !== true
                            anchors.fill: parent
                            radius: Theme.cornerRadius
                            color: itemMouse.containsMouse && modelData.enabled !== false
                                   ? Theme.chipSurface : "transparent"
                            opacity: modelData.enabled === false ? 0.45 : 1

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingS
                                anchors.rightMargin: Theme.spacingS
                                spacing: Theme.spacingS

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 18
                                    text: modelData.toggle_state ? "✓" : ""
                                    color: Theme.primary
                                    font.pixelSize: Theme.fontSizeMedium
                                }

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 44
                                    text: modelData.label || ""
                                    color: Theme.surfaceText
                                    font.pixelSize: Theme.fontSizeMedium
                                    elide: Text.ElideRight
                                }

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.children && modelData.children.length > 0 ? "›" : ""
                                    color: Theme.surfaceText
                                    font.pixelSize: Theme.fontSizeLarge
                                }
                            }

                            MouseArea {
                                id: itemMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                enabled: modelData.enabled !== false
                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: {
                                    if (modelData.children && modelData.children.length > 0)
                                        root.navigation = root.navigation.concat([index]);
                                    else
                                        root.activate(modelData);
                                }
                            }
                        }
                    }
                }

                StyledText {
                    visible: root.visibleItems.length === 0
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.menuState.status === "starting" ? "Đang khởi động…" : "Không có mục menu"
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeMedium
                }
            }
        }
    }

    popoutWidth: 330
    popoutHeight: Math.min(620, 150 + visibleItems.length * 40)
}

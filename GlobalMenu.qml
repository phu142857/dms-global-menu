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
    readonly property bool menuPopoutActive: anchoredMenuPopout.shouldBeVisible
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

    function openMenu(index, anchorItem) {
        selectedMenu = index;
        navigation = [];
        surfaceContext?.ensureVisible(root);
        const itemAnchor = surfaceContext?.popupAnchor(anchorItem, section);
        if (itemAnchor) {
            // DPopout normally centres itself on the trigger. Shift the
            // trigger so the popout's left edge lines up with the clicked
            // top-level menu, matching the macOS menu bar.
            const leftAlignedX = itemAnchor.trigger.x
                               + (root.popoutWidth - itemAnchor.trigger.width) / 2;
            anchoredMenuPopout.setTriggerPosition(
                leftAlignedX, itemAnchor.trigger.y, itemAnchor.trigger.width,
                itemAnchor.section, itemAnchor.screen, itemAnchor.position,
                itemAnchor.thickness, itemAnchor.spacing, itemAnchor.config,
                anchorItem);
            PopoutManager.requestPopout(anchoredMenuPopout, undefined,
                                         popoutTriggerId + ":" + index);
            return;
        }

        const fallbackAnchor = pillAnchor();
        if (!fallbackAnchor)
            return;
        const fallbackX = fallbackAnchor.trigger.x
                        + (root.popoutWidth - fallbackAnchor.trigger.width) / 2;
        anchoredMenuPopout.setTriggerPosition(
            fallbackX, fallbackAnchor.trigger.y,
            fallbackAnchor.trigger.width, section, fallbackAnchor.screen,
            fallbackAnchor.position, fallbackAnchor.thickness,
            fallbackAnchor.spacing, fallbackAnchor.config, root);
        PopoutManager.requestPopout(anchoredMenuPopout, undefined,
                                     popoutTriggerId + ":" + index);
    }

    function activate(item) {
        if (!item || item.enabled === false || !item.token)
            return;
        runBackend(["activate", item.token]);
        anchoredMenuPopout.close();
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
                width: appLabel.implicitWidth + 24

                StyledText {
                    id: appLabel
                    anchors.centerIn: parent
                    text: root.menuState.app_name || "Desktop"
                    color: Theme.surfaceText
                    font.pixelSize: root.textSize
                    font.family: "Inter"
                    font.weight: Font.Bold
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
                    width: menuLabel.implicitWidth + 20

                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 3
                        anchors.bottomMargin: 3
                        radius: 8
                        color: menuMouse.containsMouse || root.selectedMenu === index && root.menuPopoutActive
                               ? Theme.withAlpha(Theme.surfaceText, 0.12) : "transparent"
                    }

                    StyledText {
                        id: menuLabel
                        anchors.centerIn: parent
                        text: modelData.label || ""
                        color: Theme.surfaceText
                        font.pixelSize: root.textSize
                        font.family: "Inter"
                        font.weight: Font.Normal
                    }

                    MouseArea {
                        id: menuMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openMenu(index, menuMouse)
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

    popoutContent: null

    property Component anchoredMenuContent: Component {
        PopoutComponent {
            id: menuPopout
            headerText: ""
            detailsText: ""

            Column {
                width: parent.width
                spacing: 2

                Rectangle {
                    visible: root.navigation.length > 0
                    width: parent.width
                    height: visible ? 32 : 0
                    radius: 8
                    color: backMouse.containsMouse ? Theme.withAlpha(Theme.surfaceText, 0.10) : "transparent"

                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.spacingS

                        DIcon {
                            name: "arrow_back"
                            size: Theme.fontSizeLarge
                            color: Theme.surfaceText
                        }

                        StyledText {
                            text: "Back"
                            color: Theme.surfaceText
                            font.pixelSize: 13
                            font.family: "Inter"
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
                        height: modelData.separator ? 9 : 32
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
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            radius: 8
                            color: itemMouse.containsMouse && modelData.enabled !== false
                                   ? Theme.primary : "transparent"
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
                                    color: itemMouse.containsMouse ? Theme.primaryText : Theme.primary
                                    font.pixelSize: 13
                                    font.family: "Inter"
                                }

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 44
                                    text: modelData.label || ""
                                    color: itemMouse.containsMouse && modelData.enabled !== false
                                           ? Theme.primaryText : Theme.surfaceText
                                    font.pixelSize: 13
                                    font.family: "Inter"
                                    elide: Text.ElideRight
                                }

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.children && modelData.children.length > 0 ? "›" : ""
                                    color: itemMouse.containsMouse && modelData.enabled !== false
                                           ? Theme.primaryText : Theme.surfaceText
                                    font.pixelSize: 16
                                    font.family: "Inter"
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
                    text: root.menuState.status === "starting" ? "Starting…" : "No Menu Items"
                    color: Theme.surfaceVariantText
                    font.pixelSize: 13
                    font.family: "Inter"
                }
            }
        }
    }

    PluginPopout {
        id: anchoredMenuPopout
        pluginId: root.pluginId
        contentWidth: root.popoutWidth
        contentHeight: root.popoutHeight
        pluginContent: root.anchoredMenuContent
    }

    popoutWidth: 300
    popoutHeight: Math.max(64, Math.min(560, 16 + visibleItems.length * 34
                                       + (navigation.length > 0 ? 34 : 0)))
}

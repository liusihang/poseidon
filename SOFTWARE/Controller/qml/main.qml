import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs 1.3

ApplicationWindow {
    id: win
    visible: true
    width: 1024; height: 600
    title: "Poseidon Touch (QML)"

    Material.theme: Material.Dark
    Material.accent: Material.Blue

    header: ToolBar {
        RowLayout { anchors.fill: parent; spacing: 12; leftPadding: 12; rightPadding: 12 }
        Label { text: win.title; font.pixelSize: 22; Layout.alignment: Qt.AlignVCenter }
        Item { Layout.fillWidth: true }
        Button { text: "两板置零"; onClicked: backend.zeroAll() }
        Button { text: "紧急停止"; onClicked: backend.estopAll() }
    }

    TabView {
        anchors.fill: parent
        Tab { title: "控制";  ControlPage { anchors.fill: parent } }
        Tab { title: "连接";  PortsPage { anchors.fill: parent } }
        Tab { title: "校准";  CalibPage { anchors.fill: parent } }
        Tab { title: "日志";   LogPage   { anchors.fill: parent } }
    }
}

// ============ 控制页：四泵 2×2 ============
Component {
    id: ControlPage
    Item {
        GridLayout {
            anchors.fill: parent; anchors.margins: 16
            columns: 2; rowSpacing: 16; columnSpacing: 16
            PumpCard { pid: 1 }
            PumpCard { pid: 2 }
            PumpCard { pid: 3 }
            PumpCard { pid: 4 }
        }
    }
}

// ============ 连接页 ============
Component {
    id: PortsPage
    Item {
        function refresh() { portsModel = backend.listPorts() }
        property var portsModel: []

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 16

            GroupBox {
                title: "主板 (P1/P2)"
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 12
                    ComboBox { id: cbA; Layout.fillWidth: true; model: parent.parent.parent.portsModel }
                    ComboBox { id: baudA; width: 140; model: ["230400","115200","250000"]; currentIndex: 0 }
                    Button { text: "连接"; onClicked: backend.openBoard(0, cbA.currentText, parseInt(baudA.currentText)) }
                }
            }

            GroupBox {
                title: "副板 (P3/P4)"
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 12
                    ComboBox { id: cbB; Layout.fillWidth: true; model: parent.parent.parent.portsModel }
                    ComboBox { id: baudB; width: 140; model: ["230400","115200","250000"]; currentIndex: 0 }
                    Button { text: "连接"; onClicked: backend.openBoard(1, cbB.currentText, parseInt(baudB.currentText)) }
                }
            }

            RowLayout { spacing: 12
                Button { text: "刷新端口"; onClicked: refresh() }
                Button { text: "全部断开"; onClicked: backend.closeAll() }
            }
            Item { Layout.fillHeight: true }
        }

        Component.onCompleted: refresh()
    }
}

// ============ 校准页 ============
Component {
    id: CalibPage
    Flickable {
        anchors.fill: parent; contentWidth: parent.width; contentHeight: col.implicitHeight; clip: true
        ColumnLayout { id: col; anchors.margins: 24; width: parent.width; spacing: 16
            Repeater { model: [1,2,3,4]
                delegate: Frame {
                    Layout.fillWidth: true
                    ColumnLayout { anchors.margins: 12; spacing: 8
                        Label { text: `泵 ${modelData} 校准` ; font.pixelSize: 20 }
                        RowLayout { spacing: 8
                            Button { text: "打开向导"; onClicked: calibDlg.openFor(modelData) }
                            CheckBox { id: inv; text: "反向"; checked: backend.getInvert(modelData);
                                onToggled: backend.setInvert(modelData, checked)
                            }
                        }
                        Label { text: `当前 steps/mm: ${backend.getStepsPerMm(modelData).toFixed(3)}` }
                    }
                }
            }
            Item { Layout.fillHeight: true }
        }
        CalibrationDialog { id: calibDlg }
    }
}

// ============ 日志页 ============
Component {
    id: LogPage
    Item {
        property string buf: ""
        function append(s) {
            buf += s + "
"; txLog.text = buf; txLog.cursorPosition = buf.length
        }
        Connections { target: backend; onLogLine: append(arguments[0]) }
        TextArea { id: txLog; anchors.fill: parent; wrapMode: TextArea.NoWrap; readOnly: true; font.family: "Monaco"; font.pixelSize: 14 }
    }
}
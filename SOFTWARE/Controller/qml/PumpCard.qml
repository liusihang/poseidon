import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    property int pid: 1
    implicitWidth: 480; implicitHeight: 260

    Rectangle {
        anchors.fill: parent
        radius: 16; color: "#1f2937"; border.color: "#374151"; border.width: 2
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 16; spacing: 8
            Label { text: `Pump ${root.pid}`; font.pixelSize: 22 }

            RowLayout { spacing: 8
                ComboBox { id: cbSyr; Layout.preferredWidth: 260; model: backend.syringeNames(); onCurrentTextChanged: updateDiam() }
                Label { id: lbDiam; text: "Ø -- mm" }
                Button { text: "编辑库"; onClicked: syrDlg.openEditor() }
            }

            RowLayout { spacing: 8
                TextField { id: spd; text: "0.50"; inputMethodHints: Qt.ImhFormattedNumbersOnly; Layout.preferredWidth: 120 }
                ComboBox { id: spdUnit; model: ["mL/min","mL/s","mm/s"]; Layout.preferredWidth: 120 }
                Button { text: "设速度"; onClicked: backend.setSpeed(root.pid, parseFloat(spd.text||"0"), spdUnit.currentText) }
                TextField { id: acc; text: "5.0"; inputMethodHints: Qt.ImhFormattedNumbersOnly; Layout.preferredWidth: 120 }
                ComboBox { id: accUnit; model: ["mL/s²","mm/s²"]; Layout.preferredWidth: 110 }
                Button { text: "设加速度"; onClicked: backend.setAccel(root.pid, parseFloat(acc.text||"0"), accUnit.currentText) }
            }

            RowLayout { spacing: 8
                TextField { id: vol; text: "1.000"; inputMethodHints: Qt.ImhFormattedNumbersOnly; Layout.preferredWidth: 140 }
                ComboBox { id: volUnit; model: ["mL","uL","mm"]; Layout.preferredWidth: 100 }
                Button { text: "运行"; Layout.fillWidth: true; onClicked: backend.run(root.pid, parseFloat(vol.text||"0"), volUnit.currentText) }
                Button { text: "暂停"; onClicked: backend.pausePump(root.pid) }
                Button { text: "停止"; onClicked: backend.stopPump(root.pid) }
            }

            RowLayout { spacing: 8
                TextField { id: jogV; text: "0.100"; inputMethodHints: Qt.ImhFormattedNumbersOnly; Layout.preferredWidth: 140 }
                ComboBox { id: jogUnit; model: ["mL","uL","mm"]; Layout.preferredWidth: 100 }
                Button { text: "◀︎ JOG"; onClicked: backend.jog(root.pid, -parseFloat(jogV.text||"0"), jogUnit.currentText) }
                Button { text: "JOG ▶︎"; onClicked: backend.jog(root.pid, +parseFloat(jogV.text||"0"), jogUnit.currentText) }
                Label { id: lbState; text: "状态：—"; font.pixelSize: 16; color: "#e5e7eb"; Layout.fillWidth: true }
            }

            Connections {
                target: backend
                onAckChanged: (p1,p2,p3,p4)=>{
                    var rem = [p1,p2,p3,p4][root.pid-1]
                    // steps→mm 与 mL 的估算只在后端已知注射器/steps/mm 情况下有意义，这里展示剩余步数为主
                    lbState.text = `状态：余步 ${rem}`
                }
            }
        }
    }

    function updateDiam(){ lbDiam.text = `Ø ${backend.syringeDiameter(cbSyr.currentText).toFixed(3)} mm` }
    Component.onCompleted: updateDiam()

    SyringeEditor { id: syrDlg }
}
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Dialog {
    id: dlg
    modal: true
    standardButtons: Dialog.Ok | Dialog.Cancel
    property int pumpId: 1

    title: `泵 ${pumpId} 校准向导`
    width: 560; height: 420

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 10

        GroupBox { title: "步骤 1/3：初值"
            Layout.fillWidth: true
            GridLayout { columns: 2; anchors.margins: 10; rowSpacing: 8; columnSpacing: 8
                Label { text: "steps/mm 初值" }
                TextField { id: spm0; text: backend.getStepsPerMm(dlg.pumpId).toFixed(3) }
            }
        }

        GroupBox { title: "步骤 2/3：行程校准（标尺法）"
            Layout.fillWidth: true
            GridLayout { columns: 3; anchors.margins: 10; rowSpacing: 8; columnSpacing: 8
                Label { text: "计划移动 (mm)" }
                TextField { id: planMm; text: "10.000" }
                Button { text: "执行"; onClicked: backend.run(dlg.pumpId, parseFloat(planMm.text||"0"), "mm") }
                Label { text: "实测位移 (mm)" }
                TextField { id: measMm; text: "10.000" }
                Button { text: "计算修正"; onClicked: spm1.text = backend.applyTravelCalibration(dlg.pumpId, parseFloat(planMm.text||"0"), parseFloat(measMm.text||"0")).toFixed(3) }
            }
        }

        GroupBox { title: "步骤 3/3：体积闭环（可选）"
            Layout.fillWidth: true
            GridLayout { columns: 3; anchors.margins: 10; rowSpacing: 8; columnSpacing: 8
                Label { text: "目标体积 (mL)" }
                TextField { id: planMl; text: "1.000" }
                Button { text: "注出"; onClicked: backend.run(dlg.pumpId, parseFloat(planMl.text||"0"), "mL") }
                Label { text: "实测体积 (mL)" }
                TextField { id: measMl; text: "1.000" }
                Button { text: "计算修正"; onClicked: spm1.text = backend.applyVolumeCalibration(dlg.pumpId, parseFloat(planMl.text||"0"), parseFloat(measMl.text||"0"), "BD 1 mL (Plastipak)").toFixed(3) }
            }
        }

        RowLayout { spacing: 8
            Label { text: "当前 steps/mm" }
            TextField { id: spm1; readOnly: true; text: backend.getStepsPerMm(dlg.pumpId).toFixed(3) }
            CheckBox { id: inv; text: "反向"; checked: backend.getInvert(dlg.pumpId); onToggled: backend.setInvert(dlg.pumpId, checked) }
            Item { Layout.fillWidth: true }
        }
    }

    function openFor(p){ dlg.pumpId = p; spm0.text = backend.getStepsPerMm(p).toFixed(3); spm1.text = spm0.text; inv.checked = backend.getInvert(p); dlg.open() }
}
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Dialog {
    id: dlg
    modal: true
    title: "注射器库"
    width: 520; height: 420
    standardButtons: Dialog.Ok | Dialog.Cancel

    property var rows: []

    ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 8
        Frame { Layout.fillWidth: true; Layout.fillHeight: true
            ListView {
                id: lv
                anchors.fill: parent
                model: rows
                delegate: RowLayout {
                    width: parent.width; spacing: 8
                    TextField { text: modelData.name; onTextChanged: modelData.name = text; Layout.fillWidth: true }
                    TextField { text: Number(modelData.inner_d_mm).toFixed(3); onTextChanged: modelData.inner_d_mm = parseFloat(text||"0"); width: 120 }
                }
            }
        }
        RowLayout {
            Button { text: "新增"; onClicked: rows.push({name:"Custom", inner_d_mm:10.000}) }
            Button { text: "删除"; onClicked: { if (lv.currentIndex>=0) rows.splice(lv.currentIndex,1) } }
            Item { Layout.fillWidth: true }
            Button { text: "保存"; onClicked: { backend.updateSyringes(rows); dlg.close() } }
        }
    }

    function openEditor(){ rows = backend.syringeNames().map(function(n){ return {name: n, inner_d_mm: backend.syringeDiameter(n)} }); open() }
}
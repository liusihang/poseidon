"""Touch-optimised Poseidon pump controller GUI.

This standalone PyQt5 application targets a 1024x600 touch display.
It manages two Arduino Uno controller boards (primary & secondary),
provides syringe presets, guided calibration, and live pump feedback.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - runtime dependency
    serial = None  # type: ignore

APP_NAME = "Poseidon Touch"
CONFIG_PATH = Path.home() / ".poseidon_pump_calibration.json"
BAUD_RATE = 230_400

PUMP_IDS = (1, 2, 3, 4)
PRIMARY_PUMPS = {1, 2}
SECONDARY_PUMPS = {3, 4}

SYRINGE_LIBRARY: Dict[str, float] = {
    "1 mL (BD 309628)": 14.5,
    "3 mL (BD 309657)": 8.7,
    "5 mL (BD 309646)": 12.1,
    "10 mL (BD 309604)": 14.5,
    "20 mL (BD 302830)": 19.1,
    "50 mL (BD 309653)": 26.6,
}


@dataclass
class PumpState:
    pump_id: int
    syringe_label: str = "10 mL (BD 309604)"
    plunger_area_mm2: float = 165.0  # derived from syringe selection
    steps_per_ul: float = 1.0
    target_speed: float = 600.0
    target_accel: float = 400.0
    jog_delta_ul: float = 10.0
    distance_to_go: int = 0

    def volume_to_steps(self, ul: float) -> int:
        return int(round(self.steps_per_ul * ul))


class SerialReaderThread(QtCore.QThread):
    ackReceived = QtCore.pyqtSignal(list)
    statusMessage = QtCore.pyqtSignal(str)

    def __init__(self, port: serial.Serial, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._serial = port
        self._running = threading.Event()
        self._running.set()

    def run(self) -> None:  # pragma: no cover - thread loop
        buffer = ""
        while self._running.is_set() and self._serial.is_open:
            try:
                data = self._serial.read(self._serial.in_waiting or 1)
            except serial.SerialException as exc:  # type: ignore[attr-defined]
                self.statusMessage.emit(f"Serial read error: {exc}")
                break
            if not data:
                self.msleep(2)
                continue
            buffer += data.decode(errors="ignore")
            while "<" in buffer and ">" in buffer:
                start = buffer.find("<")
                end = buffer.find(">", start)
                if end == -1:
                    break
                frame = buffer[start + 1 : end]
                buffer = buffer[end + 1 :]
                tokens = [tok.strip() for tok in frame.split(",") if tok.strip()]
                if len(tokens) == 4:
                    try:
                        values = [int(float(tok)) for tok in tokens]
                    except ValueError:
                        continue
                    self.ackReceived.emit(values)
        self.statusMessage.emit("Serial reader stopped")

    def stop(self) -> None:
        self._running.clear()
        self.wait(200)


class SerialPumpLink(QtCore.QObject):
    ackReceived = QtCore.pyqtSignal(int, int, int, int)
    statusMessage = QtCore.pyqtSignal(str)

    def __init__(self, board_role: str, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.board_role = board_role
        self._serial: Optional[serial.Serial] = None  # type: ignore[type-arg]
        self._reader: Optional[SerialReaderThread] = None
        self._lock = threading.Lock()

    @property
    def pumps(self) -> Tuple[int, int]:
        return (1, 2) if self.board_role == "primary" else (3, 4)

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port_name: str) -> bool:
        if serial is None:
            self.statusMessage.emit("pyserial not installed")
            return False
        self.disconnect()
        try:
            self._serial = serial.Serial(port=port_name, baudrate=BAUD_RATE, timeout=0.02)
        except Exception as exc:  # pragma: no cover - hardware failure path
            self.statusMessage.emit(f"Failed to open {port_name}: {exc}")
            self._serial = None
            return False
        self.statusMessage.emit(f"Connected to {port_name} ({self.board_role})")
        self._reader = SerialReaderThread(self._serial)
        self._reader.ackReceived.connect(lambda values: self.ackReceived.emit(*values))
        self._reader.statusMessage.connect(self.statusMessage.emit)
        self._reader.start()
        return True

    def disconnect(self) -> None:
        if self._reader:
            self._reader.stop()
            self._reader = None
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self.statusMessage.emit(f"Disconnected ({self.board_role})")

    def send(self, payload: str) -> None:
        if not self.is_connected():
            self.statusMessage.emit(f"{self.board_role.title()} board not connected")
            return
        frame = f"<{payload}>"
        with self._lock:
            try:
                assert self._serial is not None
                self._serial.write(frame.encode())
            except Exception as exc:  # pragma: no cover - hardware path
                self.statusMessage.emit(f"Serial write failed: {exc}")


class PumpCard(QtWidgets.QGroupBox):
    settingsChanged = QtCore.pyqtSignal(int)
    jogRequested = QtCore.pyqtSignal(int, str)
    runRequested = QtCore.pyqtSignal(int, float, str)

    def __init__(self, pump_state: PumpState, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.state = pump_state
        self.setTitle(f"Pump {pump_state.pump_id}")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.setStyleSheet("QGroupBox{font-size:20px;font-weight:bold;margin-top:24px;}"
                           "QGroupBox::title{subcontrol-origin:margin;left:16px;padding:0 8px;}")
        self._build_ui()
        self._refresh_from_state()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignLeft)

        self.syringe_combo = QtWidgets.QComboBox()
        self.syringe_combo.addItems(sorted(SYRINGE_LIBRARY.keys()))
        form.addRow("Syringe", self.syringe_combo)

        self.area_display = QtWidgets.QLabel()
        form.addRow("Area (mm²)", self.area_display)

        self.steps_edit = QtWidgets.QDoubleSpinBox()
        self.steps_edit.setRange(0.1, 20000.0)
        self.steps_edit.setDecimals(2)
        self.steps_edit.setSuffix(" steps/µL")
        form.addRow("Steps per µL", self.steps_edit)

        self.speed_edit = QtWidgets.QDoubleSpinBox()
        self.speed_edit.setRange(1.0, 5000.0)
        self.speed_edit.setSuffix(" steps/s")
        form.addRow("Speed", self.speed_edit)

        self.accel_edit = QtWidgets.QDoubleSpinBox()
        self.accel_edit.setRange(1.0, 20000.0)
        self.accel_edit.setSuffix(" steps/s²")
        form.addRow("Accel", self.accel_edit)

        self.jog_spin = QtWidgets.QDoubleSpinBox()
        self.jog_spin.setRange(0.1, 10000.0)
        self.jog_spin.setSuffix(" µL")
        form.addRow("Jog Δ", self.jog_spin)

        layout.addLayout(form)

        jog_layout = QtWidgets.QHBoxLayout()
        self.jog_backward = QtWidgets.QPushButton("◀ Retract")
        self.jog_forward = QtWidgets.QPushButton("Advance ▶")
        for btn in (self.jog_backward, self.jog_forward):
            btn.setMinimumHeight(48)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
        jog_layout.addWidget(self.jog_backward)
        jog_layout.addWidget(self.jog_forward)
        layout.addLayout(jog_layout)

        run_layout = QtWidgets.QHBoxLayout()
        self.volume_spin = QtWidgets.QDoubleSpinBox()
        self.volume_spin.setRange(0.1, 10_000.0)
        self.volume_spin.setSuffix(" µL")
        run_layout.addWidget(self.volume_spin)

        self.infuse_button = QtWidgets.QPushButton("Infuse")
        self.withdraw_button = QtWidgets.QPushButton("Withdraw")
        for btn in (self.infuse_button, self.withdraw_button):
            btn.setMinimumHeight(52)
            btn.setStyleSheet("QPushButton{font-size:20px;padding:12px 24px;}")
        run_layout.addWidget(self.infuse_button)
        run_layout.addWidget(self.withdraw_button)
        layout.addLayout(run_layout)

        self.d2g_label = QtWidgets.QLabel("0 steps remaining")
        self.d2g_label.setAlignment(QtCore.Qt.AlignCenter)
        self.d2g_label.setStyleSheet("QLabel{font-size:18px;color:#bbbbbb;padding:8px;}")
        layout.addWidget(self.d2g_label)

        layout.addStretch()

        # connections
        self.syringe_combo.currentTextChanged.connect(lambda _=None: self._update_area_from_combo())
        for widget in (self.steps_edit, self.speed_edit, self.accel_edit, self.jog_spin):
            widget.valueChanged.connect(lambda _=0, pid=self.state.pump_id: self.settingsChanged.emit(pid))
        self.jog_backward.clicked.connect(lambda: self.jogRequested.emit(self.state.pump_id, "B"))
        self.jog_forward.clicked.connect(lambda: self.jogRequested.emit(self.state.pump_id, "F"))
        self.infuse_button.clicked.connect(lambda: self.runRequested.emit(self.state.pump_id, self.volume_spin.value(), "F"))
        self.withdraw_button.clicked.connect(lambda: self.runRequested.emit(self.state.pump_id, self.volume_spin.value(), "B"))

    def _update_area_from_combo(self, emit_change: bool = True) -> None:
        label = self.syringe_combo.currentText()
        diameter = SYRINGE_LIBRARY.get(label, 0.0)
        if diameter > 0:
            radius = diameter / 2.0
            area = math.pi * radius * radius
            self.state.syringe_label = label
            self.state.plunger_area_mm2 = area
            self.area_display.setText(f"{area:.1f}")
            if emit_change:
                self.settingsChanged.emit(self.state.pump_id)

    def _refresh_from_state(self) -> None:
        self.syringe_combo.blockSignals(True)
        idx = self.syringe_combo.findText(self.state.syringe_label)
        if idx >= 0:
            self.syringe_combo.setCurrentIndex(idx)
        else:
            self.syringe_combo.setCurrentIndex(0)
        self.syringe_combo.blockSignals(False)

        for widget, value in (
            (self.steps_edit, self.state.steps_per_ul),
            (self.speed_edit, self.state.target_speed),
            (self.accel_edit, self.state.target_accel),
            (self.jog_spin, self.state.jog_delta_ul),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        self._update_area_from_combo(emit_change=False)

    def sync_to_state(self) -> None:
        self.state.steps_per_ul = self.steps_edit.value()
        self.state.target_speed = self.speed_edit.value()
        self.state.target_accel = self.accel_edit.value()
        self.state.jog_delta_ul = self.jog_spin.value()

    def set_distance_to_go(self, steps: int) -> None:
        self.d2g_label.setText(f"{steps} steps remaining")


class CalibrationDialog(QtWidgets.QDialog):
    calibrationReady = QtCore.pyqtSignal(float)

    def __init__(self, pump_state: PumpState, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Calibrate Pump {pump_state.pump_id}")
        self.setModal(True)
        self.resize(480, 320)
        self.state = pump_state
        layout = QtWidgets.QVBoxLayout(self)

        instructions = QtWidgets.QLabel(
            "<h2>Guided Calibration</h2>"
            "<ol>"
            "<li>Attach the selected syringe to the pump.</li>"
            "<li>Prime the line until fluid is just visible at the tip.</li>"
            "<li>Mount a precise measuring tube or scale.</li>"
            "<li>Press <b>Start Move</b> to dispense exactly 1000 µL.</li>"
            "<li>Measure the actual volume dispensed and enter it below.</li>"
            "</ol>"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.start_button = QtWidgets.QPushButton("Start Move (1000 µL)")
        self.start_button.setMinimumHeight(48)
        layout.addWidget(self.start_button)

        form = QtWidgets.QFormLayout()
        self.measured_spin = QtWidgets.QDoubleSpinBox()
        self.measured_spin.setRange(0.1, 5000.0)
        self.measured_spin.setValue(1000.0)
        self.measured_spin.setSuffix(" µL")
        form.addRow("Measured volume", self.measured_spin)

        layout.addLayout(form)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        self.start_button.clicked.connect(self._emit_move_request)
        button_box.accepted.connect(self._accept)
        button_box.rejected.connect(self.reject)

    moveRequested = QtCore.pyqtSignal(float)

    def _emit_move_request(self) -> None:
        self.moveRequested.emit(1000.0)

    def _accept(self) -> None:
        measured = self.measured_spin.value()
        if measured <= 0:
            QtWidgets.QMessageBox.warning(self, "Invalid measurement", "Measured volume must be greater than zero.")
            return
        # steps per µL scaling factor = commanded_steps / measured_volume
        commanded_ul = 1000.0
        scale = commanded_ul / measured
        self.calibrationReady.emit(scale)
        self.accept()


class PoseidonMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1024, 600)
        self.setStyleSheet(
            "QMainWindow{background-color:#121212;color:#f0f0f0;}"
            "QLabel{font-size:18px;}"
            "QComboBox,QDoubleSpinBox{font-size:18px;min-height:36px;}"
            "QPushButton{font-size:18px;padding:10px 14px;border-radius:8px;background-color:#1f6feb;color:white;}"
            "QPushButton:disabled{background-color:#404040;}"
        )

        self.primary_link = SerialPumpLink("primary")
        self.secondary_link = SerialPumpLink("secondary")

        self.primary_link.ackReceived.connect(self._update_from_ack)
        self.secondary_link.ackReceived.connect(self._update_from_ack)
        self.primary_link.statusMessage.connect(self._show_status)
        self.secondary_link.statusMessage.connect(self._show_status)

        self.pump_states: Dict[int, PumpState] = {pid: PumpState(pid) for pid in PUMP_IDS}
        self._load_saved_state()

        self._build_ui()

    # ------------------------- UI builders -------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root_layout = QtWidgets.QHBoxLayout(central)

        # left column: pump cards in a stacked grid
        pump_container = QtWidgets.QWidget()
        pump_layout = QtWidgets.QGridLayout(pump_container)
        pump_layout.setSpacing(16)

        self.pump_cards: Dict[int, PumpCard] = {}
        for idx, pid in enumerate(PUMP_IDS):
            card = PumpCard(self.pump_states[pid])
            row = idx // 2
            col = idx % 2
            pump_layout.addWidget(card, row, col)
            card.settingsChanged.connect(self._pump_settings_changed)
            card.jogRequested.connect(self._handle_jog)
            card.runRequested.connect(self._handle_run)
            self.pump_cards[pid] = card

        root_layout.addWidget(pump_container, 2)

        # right column: setup and calibration utilities
        side_panel = QtWidgets.QTabWidget()
        side_panel.setTabPosition(QtWidgets.QTabWidget.West)
        side_panel.setStyleSheet("QTabBar::tab{width:180px;font-size:18px;padding:18px;}"
                                 "QTabBar::tab:selected{background:#1f6feb;color:white;}"
                                 "QTabWidget::pane{border:1px solid #2c2c2c;margin:8px;}")

        side_panel.addTab(self._build_connection_tab(), "Connections")
        side_panel.addTab(self._build_calibration_tab(), "Calibration")
        side_panel.addTab(self._build_logging_tab(), "Log")

        root_layout.addWidget(side_panel, 1)

        self.status_bar = QtWidgets.QStatusBar()
        self.status_bar.setStyleSheet("QStatusBar{font-size:18px;}")
        self.setStatusBar(self.status_bar)

        self.setCentralWidget(central)
        for card in self.pump_cards.values():
            card.sync_to_state()

    def _build_connection_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        self.primary_port_combo = QtWidgets.QComboBox()
        self.secondary_port_combo = QtWidgets.QComboBox()

        refresh_btn = QtWidgets.QPushButton("Refresh Ports")
        refresh_btn.clicked.connect(self._populate_ports)
        layout.addWidget(refresh_btn)

        layout.addWidget(QtWidgets.QLabel("Primary board (pumps 1-2)"))
        layout.addWidget(self.primary_port_combo)
        self.primary_connect_btn = QtWidgets.QPushButton("Connect Primary")
        layout.addWidget(self.primary_connect_btn)

        layout.addWidget(QtWidgets.QLabel("Secondary board (pumps 3-4)"))
        layout.addWidget(self.secondary_port_combo)
        self.secondary_connect_btn = QtWidgets.QPushButton("Connect Secondary")
        layout.addWidget(self.secondary_connect_btn)

        self.disconnect_all_btn = QtWidgets.QPushButton("Disconnect All")
        layout.addWidget(self.disconnect_all_btn)

        layout.addStretch()

        self.primary_connect_btn.clicked.connect(lambda: self._connect_board(self.primary_link, self.primary_port_combo))
        self.secondary_connect_btn.clicked.connect(lambda: self._connect_board(self.secondary_link, self.secondary_port_combo))
        self.disconnect_all_btn.clicked.connect(self._disconnect_all)
        self._populate_ports()
        return tab

    def _build_calibration_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(QtWidgets.QLabel("Select a pump to launch calibration."))

        self.calibrate_combo = QtWidgets.QComboBox()
        for pid in PUMP_IDS:
            self.calibrate_combo.addItem(f"Pump {pid}", pid)
        layout.addWidget(self.calibrate_combo)

        self.calibrate_btn = QtWidgets.QPushButton("Guided Calibration")
        layout.addWidget(self.calibrate_btn)
        self.calibrate_btn.clicked.connect(self._launch_calibration)

        self.save_btn = QtWidgets.QPushButton("Save Settings")
        layout.addWidget(self.save_btn)
        self.save_btn.clicked.connect(self._save_state)

        layout.addStretch()
        return tab

    def _build_logging_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("QPlainTextEdit{background:#0c0c0c;font-size:16px;}")
        layout.addWidget(self.log_view)

        clear_btn = QtWidgets.QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_view.clear)
        layout.addWidget(clear_btn)

        layout.addStretch()
        return tab

    # ------------------------- Serial helpers -----------------------
    def _populate_ports(self) -> None:
        self.primary_port_combo.clear()
        self.secondary_port_combo.clear()
        if serial is None:
            self._show_status("pyserial missing - install pyserial to enable serial communication")
            return
        ports = serial.tools.list_ports.comports()
        for port in ports:
            text = f"{port.device} — {port.description}"
            self.primary_port_combo.addItem(text, port.device)
            self.secondary_port_combo.addItem(text, port.device)
        if not ports:
            self.primary_port_combo.addItem("No ports found", "")
            self.secondary_port_combo.addItem("No ports found", "")

    def _connect_board(self, link: SerialPumpLink, combo: QtWidgets.QComboBox) -> None:
        device = combo.currentData()
        if not device:
            self._show_status("No serial port selected")
            return
        link.connect(device)

    def _disconnect_all(self) -> None:
        self.primary_link.disconnect()
        self.secondary_link.disconnect()

    # ------------------------- Pump control -------------------------
    def _pump_settings_changed(self, pump_id: int) -> None:
        card = self.pump_cards[pump_id]
        card.sync_to_state()
        self._send_settings(pump_id)

    def _handle_jog(self, pump_id: int, direction: str) -> None:
        state = self.pump_states[pump_id]
        steps = state.volume_to_steps(state.jog_delta_ul)
        self._send_run_dist({pump_id}, direction, steps)

    def _handle_run(self, pump_id: int, volume_ul: float, direction: str) -> None:
        if volume_ul <= 0:
            self._show_status("Volume must be positive")
            return
        steps = self.pump_states[pump_id].volume_to_steps(volume_ul)
        self._send_run_dist({pump_id}, direction, steps)

    def _send_settings(self, pump_id: int) -> None:
        state = self.pump_states[pump_id]
        link = self._link_for_pump(pump_id)
        if link is None:
            self._show_status(f"Pump {pump_id} has no connected board")
            return
        payload_speed = f"SETTING,SPEED,{pump_id},{state.target_speed:.2f},F,0,0,0,0"
        payload_accel = f"SETTING,ACCEL,{pump_id},{state.target_accel:.2f},F,0,0,0,0"
        payload_steps = f"SETTING,STEPSPERUL,{pump_id},{state.steps_per_ul:.4f},F,0,0,0,0"
        link.send(payload_speed)
        link.send(payload_accel)
        link.send(payload_steps)

    def _send_run_dist(self, pump_ids: set, direction: str, steps: int) -> None:
        mask = ''.join(str(pid) for pid in sorted(pump_ids))
        fields = [0, 0, 0, 0]
        for pid in pump_ids:
            fields[pid - 1] = steps
        payload = "RUN,DIST,{mask},0,{dir},{p1},{p2},{p3},{p4}".format(
            mask=mask,
            dir=direction,
            p1=fields[0],
            p2=fields[1],
            p3=fields[2],
            p4=fields[3],
        )
        link = self._link_for_pump(next(iter(pump_ids)))
        if link:
            link.send(payload)

    def _send_run_volume(self, pump_id: int, direction: str, ul: float) -> None:
        mask = str(pump_id)
        payload = f"RUN,VOLUME,{mask},{ul:.3f},{direction},0,0,0,0"
        link = self._link_for_pump(pump_id)
        if link:
            link.send(payload)

    def _link_for_pump(self, pump_id: int) -> Optional[SerialPumpLink]:
        if pump_id in PRIMARY_PUMPS:
            return self.primary_link
        if pump_id in SECONDARY_PUMPS:
            return self.secondary_link
        return None

    def _update_from_ack(self, p1: int, p2: int, p3: int, p4: int) -> None:
        for pid, value in zip(PUMP_IDS, (p1, p2, p3, p4)):
            if pid in self.pump_states:
                self.pump_states[pid].distance_to_go = value
                self.pump_cards[pid].set_distance_to_go(value)

    # ------------------------- Calibration -------------------------
    def _launch_calibration(self) -> None:
        pump_id = self.calibrate_combo.currentData()
        if pump_id not in self.pump_states:
            return
        dialog = CalibrationDialog(self.pump_states[pump_id], self)
        dialog.moveRequested.connect(lambda ul, pid=pump_id: self._send_run_volume(pid, "F", ul))
        dialog.calibrationReady.connect(lambda scale, pid=pump_id: self._apply_calibration(pid, scale))
        dialog.exec_()

    def _apply_calibration(self, pump_id: int, scale: float) -> None:
        state = self.pump_states[pump_id]
        state.steps_per_ul *= scale
        self._show_status(f"Pump {pump_id} calibration updated (×{scale:.3f})")
        card = self.pump_cards[pump_id]
        card.steps_edit.setValue(state.steps_per_ul)
        self._send_settings(pump_id)
        self._save_state()

    # ------------------------- Persistence -------------------------
    def _load_saved_state(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except Exception:
            return
        for pid_str, payload in data.get("pump_states", {}).items():
            pid = int(pid_str)
            if pid not in self.pump_states:
                continue
            state = self.pump_states[pid]
            state.syringe_label = payload.get("syringe_label", state.syringe_label)
            state.plunger_area_mm2 = payload.get("plunger_area_mm2", state.plunger_area_mm2)
            state.steps_per_ul = payload.get("steps_per_ul", state.steps_per_ul)
            state.target_speed = payload.get("target_speed", state.target_speed)
            state.target_accel = payload.get("target_accel", state.target_accel)
            state.jog_delta_ul = payload.get("jog_delta_ul", state.jog_delta_ul)

    def _save_state(self) -> None:
        payload = {
            "pump_states": {
                str(pid): {
                    "syringe_label": state.syringe_label,
                    "plunger_area_mm2": state.plunger_area_mm2,
                    "steps_per_ul": state.steps_per_ul,
                    "target_speed": state.target_speed,
                    "target_accel": state.target_accel,
                    "jog_delta_ul": state.jog_delta_ul,
                }
                for pid, state in self.pump_states.items()
            }
        }
        CONFIG_PATH.write_text(json.dumps(payload, indent=2))
        self._show_status("Configuration saved")

    # ------------------------- Logging ------------------------------
    def _show_status(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        if hasattr(self, "status_bar") and self.status_bar:
            self.status_bar.showMessage(message, 5000)
        if hasattr(self, "log_view") and self.log_view:
            self.log_view.appendPlainText(f"[{timestamp}] {message}")

    # ------------------------- Qt lifecycle ------------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # pragma: no cover - Qt hook
        self._save_state()
        self._disconnect_all()
        super().closeEvent(event)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = PoseidonMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()

import json
import math
import queue
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict

import serial
import serial.tools.list_ports
from PySide6 import QtCore

APP_DIR = Path.home() / ".poseidon_touch"
APP_DIR.mkdir(parents=True, exist_ok=True)
CALIB_PATH = APP_DIR / "calibration.json"
SYRINGE_PATH = APP_DIR / "syringes.json"
PUMP_NAMES_PATH = APP_DIR / "pump_names.json"

DEFAULT_BAUD = 230400
POLL_INTERVAL_SEC = 0.20

ML_TO_MM3 = 1000.0


def area_from_diameter_mm(d_mm: float) -> float:
    return math.pi * (d_mm / 2.0) ** 2


@dataclass
class PumpCalibration:
    steps_per_mm: float = 800.0
    invert_dir: bool = False

    def to_steps(self, length_mm: float) -> int:
        return int(round(length_mm * self.steps_per_mm))


@dataclass
class SyringeModel:
    name: str
    inner_d_mm: float

    @property
    def area_mm2(self) -> float:
        return area_from_diameter_mm(self.inner_d_mm)


DEFAULT_SYRINGES = [
    SyringeModel("BD 1 mL (Plastipak)", 4.699),
    SyringeModel("3 mL", 8.585),
    SyringeModel("5 mL", 12.06),
    SyringeModel("10 mL", 14.5),
    SyringeModel("20 mL", 19.13),
    SyringeModel("30 mL", 23.0),
    SyringeModel("50/60 mL", 26.59),
]


# ------- 串口链路（单板） -------
class SerialLink(QtCore.QObject):
    lineReceived = QtCore.Signal(str)
    portStatus = QtCore.Signal(bool)
    logLine = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.port_name = ""
        self.baud = DEFAULT_BAUD
        self._ser = None
        self._rx_thread = None
        self._stop = threading.Event()
        self._tx_queue = queue.Queue()

    def set_port(self, port: str, baud: int):
        self.port_name = port
        self.baud = baud

    def open(self) -> bool:
        self.close()
        if not self.port_name:
            return False
        try:
            self._ser = serial.Serial(self.port_name, self.baud, timeout=0.1)
            self._stop.clear()
            self._rx_thread = threading.Thread(target=self._io_loop, daemon=True)
            self._rx_thread.start()
            self.portStatus.emit(True)
            self.logLine.emit(f"[OPEN] {self.port_name} @ {self.baud}")
            return True
        except Exception as e:
            self.logLine.emit(f"[OPEN-ERR] {e}")
            self.portStatus.emit(False)
            self._ser = None
            return False

    def close(self):
        self._stop.set()
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.5)
        self._rx_thread = None
        try:
            if self._ser:
                self._ser.close()
        finally:
            if self._ser:
                self.logLine.emit(f"[CLOSE] {self.port_name}")
        self._ser = None
        self.portStatus.emit(False)

    def send(self, frame: str):
        if not frame.endswith('>'):
            raise ValueError("frame must end with '>'")
        self._tx_queue.put(frame)

    def _io_loop(self):
        buf = ''
        last_hb = time.time()
        while not self._stop.is_set():
            # 发送
            try:
                f = self._tx_queue.get_nowait()
                if self._ser:
                    self._ser.write(f.encode('ascii'))
                    self.logLine.emit(f"TX {f}")
            except queue.Empty:
                pass
            # 接收
            try:
                if self._ser and self._ser.in_waiting:
                    data = self._ser.read(self._ser.in_waiting).decode('ascii', errors='ignore')
                    buf += data
                    while True:
                        s = buf.find('<')
                        e = buf.find('>', s + 1)
                        if s >= 0 and e > s:
                            frame = buf[s:e + 1]
                            buf = buf[e + 1:]
                            self.logLine.emit(f"RX {frame}")
                            self.lineReceived.emit(frame)
                        else:
                            break
            except Exception as e:
                self.logLine.emit(f"[RX-ERR] {e}")
                self.close()
                break
            time.sleep(0.004)


# ------- 跨板控制器 -------
class DualBoardController(QtCore.QObject):
    ackChanged = QtCore.Signal(int, int, int, int)  # p1..p4 remaining steps
    logLine = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.links = [SerialLink(), SerialLink()]  # 0: 主板(P1,P2) 1: 副板(P3,P4)
        for i, l in enumerate(self.links):
            l.lineReceived.connect(lambda s, i=i: self._on_line(i, s))
            l.logLine.connect(self.logLine)
        self._last_d2g = [0, 0, 0, 0]
        self._lock = threading.Lock()
        # 轮询线程：发送 DELTA 获取 ACK
        self._stop = threading.Event()
        self._poll_thr = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thr.start()

    # 端口管理
    def set_board_port(self, idx: int, port: str, baud: int):
        self.links[idx].set_port(port, baud)

    def open_board(self, idx: int) -> bool:
        return self.links[idx].open()

    def close_all(self):
        for l in self.links:
            l.close()

    # 指令工具
    @staticmethod
    def _mask(pumps: List[int]) -> str:
        s = ''.join(str(p) for p in sorted(set(pumps)))
        return s or '0'

    @staticmethod
    def _frame(mode, setting, pumps, val, direction, p1, p2, p3, p4):
        return f"<{mode},{setting},{pumps},{val:.6f},{direction},{p1},{p2},{p3},{p4}>"

    # 高层 API
    def set_speed(self, pump_ids: List[int], steps_per_s: float):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            f = self._frame("SETTING", "SPEED", self._mask(b0), steps_per_s, 'F', 0, 0, 0, 0)
            self.links[0].send(f)
        if b1:
            f = self._frame("SETTING", "SPEED", self._mask(b1), steps_per_s, 'F', 0, 0, 0, 0)
            self.links[1].send(f)

    def set_accel(self, pump_ids: List[int], steps_per_s2: float):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            f = self._frame("SETTING", "ACCEL", self._mask(b0), steps_per_s2, 'F', 0, 0, 0, 0)
            self.links[0].send(f)
        if b1:
            f = self._frame("SETTING", "ACCEL", self._mask(b1), steps_per_s2, 'F', 0, 0, 0, 0)
            self.links[1].send(f)

    def run_dist(self, p1=0, p2=0, p3=0, p4=0, direction='F'):
        if p1 or p2:
            f0 = self._frame("RUN", "DIST", self._mask([p for p, s in ((1, p1), (2, p2)) if s]), 0.0, direction, p1, p2, 0, 0)
            self.links[0].send(f0)
        if p3 or p4:
            f1 = self._frame("RUN", "DIST", self._mask([p for p, s in ((3, p3), (4, p4)) if s]), 0.0, direction, 0, 0, p3, p4)
            self.links[1].send(f1)

    def stop(self, pump_ids: List[int]):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            f = self._frame("STOP", "BLAH", self._mask(b0), 0.0, 'F', 0, 0, 0, 0)
            self.links[0].send(f)
        if b1:
            f = self._frame("STOP", "BLAH", self._mask(b1), 0.0, 'F', 0, 0, 0, 0)
            self.links[1].send(f)

    def pause(self, pump_ids: List[int]):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            self.links[0].send(self._frame("PAUSE", "BLAH", self._mask(b0), 0.0, 'F', 0, 0, 0, 0))
        if b1:
            self.links[1].send(self._frame("PAUSE", "BLAH", self._mask(b1), 0.0, 'F', 0, 0, 0, 0))

    def resume(self, pump_ids: List[int]):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            self.links[0].send(self._frame("RESUME", "BLAH", self._mask(b0), 0.0, 'F', 0, 0, 0, 0))
        if b1:
            self.links[1].send(self._frame("RESUME", "BLAH", self._mask(b1), 0.0, 'F', 0, 0, 0, 0))

    def zero(self, pump_ids=None):
        if pump_ids is None:
            pump_ids = [1, 2, 3, 4]
        self._zero_subset(pump_ids)

    def _zero_subset(self, pump_ids):
        b0 = [p for p in pump_ids if p in (1, 2)]
        b1 = [p for p in pump_ids if p in (3, 4)]
        if b0:
            f0 = self._frame("ZERO", "BLAH", self._mask(b0), 0.0, 'F', 0, 0, 0, 0)
            self.links[0].send(f0)
        if b1:
            f1 = self._frame("ZERO", "BLAH", self._mask(b1), 0.0, 'F', 0, 0, 0, 0)
            self.links[1].send(f1)

    # 轮询
    def _poll_loop(self):
        while not self._stop.is_set():
            f = self._frame("SETTING", "DELTA", '0', 0.0, 'F', 0, 0, 0, 0)
            try:
                for l in self.links:
                    l.send(f)
            except Exception:
                pass
            time.sleep(POLL_INTERVAL_SEC)

    def _on_line(self, board_idx: int, frame: str):
        # 期待 <d2g1,d2g2,d2g3,d2g4>
        try:
            if not (frame.startswith('<') and frame.endswith('>')):
                return
            body = frame[1:-1]
            parts = [p.strip() for p in body.split(',')]
            if len(parts) != 4:
                return
            vals = [int(float(x)) for x in parts]
            with self._lock:
                if board_idx == 0:
                    self._last_d2g[0] = vals[0]
                    self._last_d2g[1] = vals[1]
                else:
                    self._last_d2g[2] = vals[2]
                    self._last_d2g[3] = vals[3]
                a = self._last_d2g[:]
            self.ackChanged.emit(a[0], a[1], a[2], a[3])
        except Exception:
            pass

    def last_d2g(self):
        with self._lock:
            return self._last_d2g[:]


# ------- 存储 -------
class CalibrationStore:
    def __init__(self):
        self.by_pump: Dict[int, PumpCalibration] = {i: PumpCalibration() for i in (1, 2, 3, 4)}
        self.load()

    def load(self):
        if CALIB_PATH.exists():
            try:
                obj = json.loads(CALIB_PATH.read_text())
                for k, v in obj.items():
                    self.by_pump[int(k)] = PumpCalibration(**v)
            except Exception:
                pass

    def save(self):
        obj = {str(i): asdict(self.by_pump[i]) for i in (1, 2, 3, 4)}
        CALIB_PATH.write_text(json.dumps(obj, indent=2))


class SyringeStore:
    def __init__(self):
        self.models: List[SyringeModel] = []
        self.load()

    def load(self):
        if SYRINGE_PATH.exists():
            try:
                arr = json.loads(SYRINGE_PATH.read_text())
                self.models = [SyringeModel(**x) for x in arr]
                return
            except Exception:
                pass
        self.models = DEFAULT_SYRINGES.copy()

    def save(self):
        SYRINGE_PATH.write_text(json.dumps([asdict(m) for m in self.models], indent=2))

    def names(self) -> List[str]:
        return [m.name for m in self.models]

    def by_name(self, name: str) -> SyringeModel:
        for m in self.models:
            if m.name == name:
                return m
        return self.models[0]


class PumpNameStore:
    def __init__(self):
        self.names: Dict[int, str] = {i: f"Pump {i}" for i in (1, 2, 3, 4)}
        self.load()

    def load(self):
        if PUMP_NAMES_PATH.exists():
            try:
                obj = json.loads(PUMP_NAMES_PATH.read_text())
                for k, v in obj.items():
                    self.names[int(k)] = str(v)
            except Exception:
                pass

    def save(self):
        data = {str(i): self.names[i] for i in (1, 2, 3, 4)}
        PUMP_NAMES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get(self, pump_id: int) -> str:
        return self.names.get(pump_id, f"Pump {pump_id}")

    def set(self, pump_id: int, name: str):
        self.names[pump_id] = name.strip() or f"Pump {pump_id}"
        self.save()


# ------- 单位换算 -------
class UnitConv:
    @staticmethod
    def vol_ml_to_length_mm(v_ml: float, syr: SyringeModel) -> float:
        return (v_ml * ML_TO_MM3) / syr.area_mm2

    @staticmethod
    def vol_ul_to_length_mm(v_ul: float, syr: SyringeModel) -> float:
        return UnitConv.vol_ml_to_length_mm(v_ul / 1000.0, syr)

    @staticmethod
    def speed_to_steps_per_s(value: float, unit: str, syr: SyringeModel, spm: float) -> float:
        if unit == 'mm/s':
            return value * spm
        if unit == 'mL/s':
            return UnitConv.vol_ml_to_length_mm(value, syr) * spm
        if unit == 'mL/min':
            return UnitConv.vol_ml_to_length_mm(value, syr) * spm / 60.0
        if unit == 'uL/min':
            return UnitConv.vol_ul_to_length_mm(value, syr) * spm / 60.0
        return value

    @staticmethod
    def accel_to_steps_per_s2(value: float, unit: str, syr: SyringeModel, spm: float) -> float:
        if unit == 'mm/s²':
            return value * spm
        if unit == 'mL/s²':
            return UnitConv.vol_ml_to_length_mm(value, syr) * spm
        return value


# ------- QML 后端桥 -------
class Backend(QtCore.QObject):
    # 状态/日志/端口
    ackChanged = QtCore.Signal(int, int, int, int)  # p1..p4
    logLine = QtCore.Signal(str)
    portsChanged = QtCore.Signal(list)

    def __init__(self):
        super().__init__()
        self.ctrl = DualBoardController()
        self.ctrl.ackChanged.connect(self.ackChanged)
        self.ctrl.logLine.connect(self.logLine)
        self.calib = CalibrationStore()
        self.syr = SyringeStore()
        self.pump_names = PumpNameStore()

    # ---------- 串口 ----------
    @QtCore.Slot(result=list)
    def listPorts(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.portsChanged.emit(ports)
        return ports

    @QtCore.Slot(int, str, int, result=bool)
    def openBoard(self, idx: int, port: str, baud: int) -> bool:
        self.ctrl.set_board_port(idx, port, baud)
        ok = self.ctrl.open_board(idx)
        return ok

    @QtCore.Slot()
    def closeAll(self):
        self.ctrl.close_all()

    @QtCore.Slot()
    def zeroAll(self):
        self.ctrl.zero()

    @QtCore.Slot(int)
    def zeroPump(self, pumpId: int):
        self.ctrl.zero([pumpId])

    @QtCore.Slot()
    def estopAll(self):
        self.ctrl.stop([1, 2, 3, 4])

    # ---------- 注射器 ----------
    @QtCore.Slot(result=list)
    def syringeNames(self) -> List[str]:
        return self.syr.names()

    @QtCore.Slot(str, result=float)
    def syringeDiameter(self, name: str) -> float:
        return self.syr.by_name(name).inner_d_mm

    @QtCore.Slot(list)
    def updateSyringes(self, arr):
        models = []
        for x in arr:
            name = str(x.get('name', 'Model'))
            dmm = float(x.get('inner_d_mm', 10.0))
            models.append(SyringeModel(name, dmm))
        self.syr.models = models
        self.syr.save()

    @QtCore.Slot(result=list)
    def pumpNames(self) -> List[str]:
        return [self.pump_names.get(i) for i in (1, 2, 3, 4)]

    @QtCore.Slot(int, str)
    def setPumpName(self, pumpId: int, name: str):
        self.pump_names.set(pumpId, name)

    # ---------- 校准 ----------
    @QtCore.Slot(int, result=float)
    def getStepsPerMm(self, pumpId: int) -> float:
        return float(self.calib.by_pump[pumpId].steps_per_mm)

    @QtCore.Slot(int, float)
    def setStepsPerMm(self, pumpId: int, v: float):
        self.calib.by_pump[pumpId].steps_per_mm = float(v)
        self.calib.save()

    @QtCore.Slot(int, bool)
    def setInvert(self, pumpId: int, inv: bool):
        self.calib.by_pump[pumpId].invert_dir = bool(inv)
        self.calib.save()

    @QtCore.Slot(int, result=bool)
    def getInvert(self, pumpId: int) -> bool:
        return bool(self.calib.by_pump[pumpId].invert_dir)

    @QtCore.Slot(int, float, float, result=float)
    def applyTravelCalibration(self, pumpId: int, plan_mm: float, meas_mm: float) -> float:
        spm0 = self.calib.by_pump[pumpId].steps_per_mm
        spm1 = spm0 * (plan_mm / max(0.001, meas_mm))
        self.calib.by_pump[pumpId].steps_per_mm = spm1
        self.calib.save()
        return float(spm1)

    @QtCore.Slot(int, float, float, str, result=float)
    def applyVolumeCalibration(self, pumpId: int, target_ml: float, meas_ml: float, syringeName: str) -> float:
        spm1 = self.calib.by_pump[pumpId].steps_per_mm
        # 体积比例修正（与注射器面积相关在长度换算中已包含，比例法仍可直接按体积比修正）
        spm2 = spm1 * (target_ml / max(0.001, meas_ml))
        self.calib.by_pump[pumpId].steps_per_mm = spm2
        self.calib.save()
        return float(spm2)

    # ---------- 运动 ----------
    @QtCore.Slot(int, float, str)
    def setSpeed(self, pumpId: int, v: float, unit: str):
        syr = self.syr.by_name(self.syr.names()[0])  # 速度与注射器无强绑定，但若需可传当前选择
        spm = self.calib.by_pump[pumpId].steps_per_mm
        steps_s = UnitConv.speed_to_steps_per_s(v, unit, syr, spm)
        self.ctrl.set_speed([pumpId], steps_s)

    @QtCore.Slot(int, float, str)
    def setAccel(self, pumpId: int, a: float, unit: str):
        syr = self.syr.by_name(self.syr.names()[0])
        spm = self.calib.by_pump[pumpId].steps_per_mm
        steps_s2 = UnitConv.accel_to_steps_per_s2(a, unit, syr, spm)
        self.ctrl.set_accel([pumpId], steps_s2)

    @QtCore.Slot(int, float, str)
    def run(self, pumpId: int, value: float, unit: str):
        # 单泵运行：体积/位移 → 步
        # 注意方向：根据 invert_dir 决定 F/B
        syr = self.syr.by_name(self.syr.names()[0])
        cal = self.calib.by_pump[pumpId]
        if unit == 'mm':
            length_mm = value
        elif unit == 'mL':
            length_mm = UnitConv.vol_ml_to_length_mm(value, syr)
        else:  # 'uL'
            length_mm = UnitConv.vol_ul_to_length_mm(value, syr)
        steps = int(round(length_mm * cal.steps_per_mm))
        direction = 'B' if cal.invert_dir else 'F'
        p = pumpId
        p1 = steps if p == 1 else 0
        p2 = steps if p == 2 else 0
        p3 = steps if p == 3 else 0
        p4 = steps if p == 4 else 0
        self.ctrl.run_dist(p1, p2, p3, p4, direction)

    @QtCore.Slot(int, float, str)
    def jog(self, pumpId: int, delta: float, unit: str):
        syr = self.syr.by_name(self.syr.names()[0])
        cal = self.calib.by_pump[pumpId]
        if unit == 'mm':
            length_mm = abs(delta)
        elif unit == 'mL':
            length_mm = UnitConv.vol_ml_to_length_mm(abs(delta), syr)
        else:
            length_mm = UnitConv.vol_ul_to_length_mm(abs(delta), syr)
        steps = int(round(length_mm * cal.steps_per_mm))
        # 负号与 invert_dir 异或决定最终方向
        direction = 'B' if ((delta < 0) ^ cal.invert_dir) else 'F'
        p = pumpId
        p1 = steps if p == 1 else 0
        p2 = steps if p == 2 else 0
        p3 = steps if p == 3 else 0
        p4 = steps if p == 4 else 0
        self.ctrl.run_dist(p1, p2, p3, p4, direction)

    @QtCore.Slot(int)
    def stopPump(self, pumpId: int):
        self.ctrl.stop([pumpId])

    @QtCore.Slot(int)
    def pausePump(self, pumpId: int):
        self.ctrl.pause([pumpId])

import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

# Ensure we can import the existing controller backend without modifying PYTHONPATH
CONTROLLER_DIR = Path(__file__).resolve().parent.parent / "Controller"
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.append(str(CONTROLLER_DIR))

from backend import (  # type: ignore  # noqa: E402
    Backend,
    DEFAULT_BAUD,
    PumpCalibration,
    SyringeModel,
)


class PoseidonService:
    """Thin wrapper around the legacy Qt backend that provides thread-safe helpers for the web API."""

    def __init__(self) -> None:
        self._backend = Backend()
        self._lock = threading.RLock()

    # ----------- Connection / Boards -----------
    def list_ports(self) -> List[str]:
        with self._lock:
            return list(self._backend.listPorts())

    def open_board(self, idx: int, port: str, baud: Optional[int] = None) -> bool:
        with self._lock:
            return bool(self._backend.openBoard(idx, port, baud or DEFAULT_BAUD))

    def close_all(self) -> None:
        with self._lock:
            self._backend.closeAll()

    def zero_all(self) -> None:
        with self._lock:
            self._backend.zeroAll()

    def zero_pump(self, pump_id: int) -> None:
        with self._lock:
            self._backend.zeroPump(pump_id)

    def estop(self) -> None:
        with self._lock:
            self._backend.estopAll()

    def resume(self, pump_ids: List[int]) -> None:
        with self._lock:
            self._backend.ctrl.resume(pump_ids)

    # ----------- Pump controls -----------
    def set_speed(self, pump_id: int, value: float, unit: str) -> None:
        with self._lock:
            self._backend.setSpeed(pump_id, float(value), unit)

    def set_accel(self, pump_id: int, value: float, unit: str) -> None:
        with self._lock:
            self._backend.setAccel(pump_id, float(value), unit)

    def run(self, pump_id: int, value: float, unit: str) -> None:
        with self._lock:
            self._backend.run(pump_id, float(value), unit)

    def jog(self, pump_id: int, delta: float, unit: str) -> None:
        with self._lock:
            self._backend.jog(pump_id, float(delta), unit)

    def stop(self, pump_id: int) -> None:
        with self._lock:
            self._backend.stopPump(pump_id)

    def pause(self, pump_id: int) -> None:
        with self._lock:
            self._backend.pausePump(pump_id)

    # ----------- Calibration -----------
    def get_calibration(self, pump_id: int) -> PumpCalibration:
        with self._lock:
            return self._backend.calib.by_pump[pump_id]

    def set_steps_per_mm(self, pump_id: int, value: float) -> None:
        with self._lock:
            self._backend.setStepsPerMm(pump_id, float(value))

    def set_invert(self, pump_id: int, invert: bool) -> None:
        with self._lock:
            self._backend.setInvert(pump_id, bool(invert))

    def apply_travel_calibration(self, pump_id: int, plan_mm: float, meas_mm: float) -> float:
        with self._lock:
            return float(self._backend.applyTravelCalibration(pump_id, float(plan_mm), float(meas_mm)))

    def apply_volume_calibration(self, pump_id: int, target_ml: float, meas_ml: float, syringe_name: str) -> float:
        with self._lock:
            return float(
                self._backend.applyVolumeCalibration(pump_id, float(target_ml), float(meas_ml), syringe_name)
            )

    # ----------- Syringes -----------
    def list_syringes(self) -> List[SyringeModel]:
        with self._lock:
            return list(self._backend.syr.models)

    def update_syringes(self, models: List[Dict[str, float]]) -> None:
        with self._lock:
            self._backend.updateSyringes(models)

    # ----------- Pump naming -----------
    def get_pump_names(self) -> Dict[int, str]:
        with self._lock:
            return {i: self._backend.pump_names.get(i) for i in (1, 2, 3, 4)}

    def set_pump_name(self, pump_id: int, name: str) -> None:
        with self._lock:
            self._backend.setPumpName(pump_id, name)

    # ----------- Status snapshots -----------
    def status(self) -> Dict[str, object]:
        with self._lock:
            boards = []
            for idx, link in enumerate(self._backend.ctrl.links):
                ser = getattr(link, "_ser", None)
                boards.append(
                    {
                        "index": idx,
                        "port": getattr(link, "port_name", ""),
                        "baud": getattr(link, "baud", DEFAULT_BAUD),
                        "is_open": bool(getattr(ser, "is_open", False)),
                    }
                )
            calib = {
                pump_id: {
                    "steps_per_mm": cal.steps_per_mm,
                    "invert_dir": cal.invert_dir,
                }
                for pump_id, cal in self._backend.calib.by_pump.items()
            }
            syringes = [asdict(model) for model in self._backend.syr.models]
            ack = self._backend.ctrl.last_d2g()
            names = {i: self._backend.pump_names.get(i) for i in (1, 2, 3, 4)}
        return {
            "boards": boards,
            "calibration": calib,
            "syringes": syringes,
            "ack": ack,
            "pump_names": names,
        }


# Shared singleton so uvicorn workers reuse hardware connection logic.
service = PoseidonService()

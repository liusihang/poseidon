from __future__ import annotations

import os
import logging
from inspect import iscoroutinefunction
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

from .hotspot import ensure_hotspot_async
from .service import DEFAULT_BAUD, service

# -----------------------------------------------------------------------------
# App & logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("poseidon.web")
logging.basicConfig(level=os.getenv("POSEIDON_LOGLEVEL", "INFO"))

app = FastAPI(title="Poseidon Web Controller", version="1.0.0")

# -----------------------------------------------------------------------------
# Static assets
# -----------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
INDEX_HTML = STATIC_DIR / "index.html"

# -----------------------------------------------------------------------------
# CORS (allow same-network access from browsers)
# -----------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 在内网测试阶段放开；若对外请收紧白名单
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Optional hotspot creation on startup (controlled by env)
#   PUMP_ENABLE_AP=1            -> enable hotspot
#   PUMP_AP_SSID=<ssid>         -> optional SSID (default: ShuofangLab_Pump)
#   PUMP_AP_PASSWORD=<pass>     -> WPA2 8–63 chars; if missing, auto-generate
#   PUMP_AP_IFNAME=wlan0        -> choose interface (default: wlan0)
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    # 允许其它初始化逻辑在此处加入；出现异常只告警不终止
    try:
        logger.info("Poseidon Web Controller starting up.")
    except Exception as e:
        logger.warning("Non-fatal init warning: %s", e)

    enable_ap = os.getenv("PUMP_ENABLE_AP", "0").lower() in ("1", "true", "yes", "on")
    if not enable_ap:
        logger.info("Hotspot creation skipped (PUMP_ENABLE_AP not set).")
        return

    ssid = os.getenv("PUMP_AP_SSID", "ShuofangLab_Pump")
    ifname = os.getenv("PUMP_AP_IFNAME", "wlan0")
    password = os.getenv("PUMP_AP_PASSWORD", "")

    # 确保密码合规；为空或长度不合规时自动生成一个安全口令
    if not (8 <= len(password) <= 63):
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(16))
        logger.info("No valid PUMP_AP_PASSWORD provided; generated one for this session.")

    try:
        if iscoroutinefunction(ensure_hotspot_async):
            await ensure_hotspot_async(ssid=ssid, password=password, ifname=ifname)
        else:
            # 兼容 ensure_hotspot_async 若为同步函数的情况
            ensure_hotspot_async(ssid=ssid, password=password, ifname=ifname)
        logger.info("Hotspot enabled: ssid=%s ifname=%s", ssid, ifname)
    except Exception as e:
        # 明确记录，但不阻断服务
        logger.warning("Hotspot creation failed: %s (service continues on LAN)", e)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _ensure_valid_pump_id(pump_id: int) -> int:
    if pump_id not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="pump_id must be 1-4")
    return pump_id


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class OpenBoardRequest(BaseModel):
    board_index: int = Field(ge=0, le=1)
    port: str
    baud: Optional[int] = Field(default=DEFAULT_BAUD, gt=0)


class SpeedRequest(BaseModel):
    value: float
    unit: str

    @validator("unit")
    def _validate_unit(cls, v: str) -> str:
        allowed = {"mm/s", "mL/s", "mL/min"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v


class AccelRequest(BaseModel):
    value: float
    unit: str

    @validator("unit")
    def _validate_unit(cls, v: str) -> str:
        allowed = {"mm/s²", "mL/s²"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v


class RunRequest(BaseModel):
    value: float
    unit: str

    @validator("unit")
    def _validate_unit(cls, v: str) -> str:
        allowed = {"mm", "mL", "uL"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v


class JogRequest(BaseModel):
    delta: float
    unit: str

    @validator("unit")
    def _validate_unit(cls, v: str) -> str:
        allowed = {"mm", "mL", "uL"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v


class StepsRequest(BaseModel):
    steps_per_mm: float = Field(gt=0.0)


class InvertRequest(BaseModel):
    invert: bool


class TravelCalibrationRequest(BaseModel):
    plan_mm: float
    meas_mm: float


class VolumeCalibrationRequest(BaseModel):
    target_ml: float
    meas_ml: float
    syringe_name: str


class SyringeModelRequest(BaseModel):
    name: str
    inner_d_mm: float = Field(gt=0)


class SyringeUpdateRequest(BaseModel):
    models: List[SyringeModelRequest]


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/api/status")
def get_status():
    return service.status()


@app.get("/api/ports")
def get_ports():
    return {"ports": service.list_ports()}


@app.post("/api/boards/open")
def open_board(payload: OpenBoardRequest):
    ok = service.open_board(payload.board_index, payload.port, payload.baud)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to open serial port")
    return {"ok": True}


@app.post("/api/boards/close-all")
def close_all():
    service.close_all()
    return {"ok": True}


@app.post("/api/boards/zero")
def zero_all():
    service.zero_all()
    return {"ok": True}


@app.post("/api/boards/estop")
def estop():
    service.estop()
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/speed")
def set_speed(pump_id: int, payload: SpeedRequest):
    service.set_speed(_ensure_valid_pump_id(pump_id), payload.value, payload.unit)
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/accel")
def set_accel(pump_id: int, payload: AccelRequest):
    service.set_accel(_ensure_valid_pump_id(pump_id), payload.value, payload.unit)
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/run")
def run(pump_id: int, payload: RunRequest):
    service.run(_ensure_valid_pump_id(pump_id), payload.value, payload.unit)
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/jog")
def jog(pump_id: int, payload: JogRequest):
    service.jog(_ensure_valid_pump_id(pump_id), payload.delta, payload.unit)
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/pause")
def pause(pump_id: int):
    service.pause(_ensure_valid_pump_id(pump_id))
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/stop")
def stop(pump_id: int):
    service.stop(_ensure_valid_pump_id(pump_id))
    return {"ok": True}


@app.post("/api/pumps/{pump_id}/resume")
def resume(pump_id: int):
    pid = _ensure_valid_pump_id(pump_id)
    service.resume([pid])
    return {"ok": True}


@app.get("/api/calibration/{pump_id}")
def get_calibration(pump_id: int):
    cal = service.get_calibration(_ensure_valid_pump_id(pump_id))
    return {"steps_per_mm": cal.steps_per_mm, "invert_dir": cal.invert_dir}


@app.post("/api/calibration/{pump_id}/steps")
def set_steps(pump_id: int, payload: StepsRequest):
    service.set_steps_per_mm(_ensure_valid_pump_id(pump_id), payload.steps_per_mm)
    return {"ok": True}


@app.post("/api/calibration/{pump_id}/invert")
def set_invert(pump_id: int, payload: InvertRequest):
    service.set_invert(_ensure_valid_pump_id(pump_id), payload.invert)
    return {"ok": True}


@app.post("/api/calibration/{pump_id}/travel")
def apply_travel(pump_id: int, payload: TravelCalibrationRequest):
    spm = service.apply_travel_calibration(_ensure_valid_pump_id(pump_id), payload.plan_mm, payload.meas_mm)
    return {"steps_per_mm": spm}


@app.post("/api/calibration/{pump_id}/volume")
def apply_volume(pump_id: int, payload: VolumeCalibrationRequest):
    spm = service.apply_volume_calibration(
        _ensure_valid_pump_id(pump_id), payload.target_ml, payload.meas_ml, payload.syringe_name
    )
    return {"steps_per_mm": spm}


@app.get("/api/syringes")
def get_syringes():
    models = [{"name": m.name, "inner_d_mm": m.inner_d_mm} for m in service.list_syringes()]
    return {"models": models}


@app.put("/api/syringes")
def update_syringes(payload: SyringeUpdateRequest):
    models = [{"name": m.name, "inner_d_mm": m.inner_d_mm} for m in payload.models]
    service.update_syringes(models)
    return {"ok": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def root():
    """Serve the bundled single-page UI."""
    if INDEX_HTML.exists():
        # FileResponse 自动处理正确的 header
        return FileResponse(INDEX_HTML)
    return HTMLResponse(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Poseidon Controller</title></head>"
        "<body><h1>Poseidon Web Controller</h1><p>Static UI not yet built.</p></body></html>"
    )


@app.on_event("shutdown")
def _shutdown():
    try:
        service.close_all()
    except Exception as e:
        logger.warning("Error during shutdown: %s", e)


def get_app() -> FastAPI:
    """Allow external ASGI servers to import the application easily."""
    return app

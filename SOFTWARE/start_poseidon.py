"""
Click-to-run launcher for Poseidon Web Controller.

Starts the FastAPI server (with hotspot bootstrap) and shows a minimal
touch-friendly status window for the Raspberry Pi display.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from typing import Any, Dict, List

import uvicorn
from PySide6 import QtCore, QtGui, QtWidgets

from SOFTWARE.WebController.server import get_app
from SOFTWARE.WebController.service import service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_preferred_ip() -> str:
    """Best-effort detection of the primary IPv4 address."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Background server runner
# ---------------------------------------------------------------------------
class UvicornRunner(threading.Thread):
    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        config = uvicorn.Config(
            get_app(),
            host=self.host,
            port=self.port,
            log_level="info",
            reload=False,
            workers=1,
        )
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = False  # Running in thread
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.server.serve())
        finally:
            self._loop.close()

    def stop(self) -> None:
        self.server.should_exit = True
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.server.shutdown(), self._loop)


# ---------------------------------------------------------------------------
# Touch status window
# ---------------------------------------------------------------------------
class StatusPoller(QtCore.QObject):
    statusUpdated = QtCore.Signal(dict)
    errorRaised = QtCore.Signal(str)

    def __init__(self, interval_ms: int = 2000):
        super().__init__()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()
        self._poll()

    def stop(self) -> None:
        self._timer.stop()

    @QtCore.Slot()
    def _poll(self) -> None:
        try:
            snapshot = service.status()
            self.statusUpdated.emit(snapshot)
        except Exception as exc:  # noqa: BLE001
            self.errorRaised.emit(str(exc))


class MainWindow(QtWidgets.QWidget):
    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self.setWindowTitle("Poseidon Touch Panel")
        self.setWindowIcon(QtGui.QIcon.fromTheme("applications-engineering"))
        self.setMinimumSize(480, 320)

        self.infoLabel = QtWidgets.QLabel(alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self.infoLabel.setWordWrap(True)
        self.infoLabel.setStyleSheet("font-size: 16px;")

        self.ackLabel = QtWidgets.QLabel("--", alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        self.ackLabel.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.urlLabel = QtWidgets.QLabel(
            f"手机浏览器访问: http://{host}:{port}/", alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.urlLabel.setStyleSheet("font-size: 18px; background-color: #1f2937; color: #f8fafc; padding: 8px;")

        btn_refresh = QtWidgets.QPushButton("刷新状态")
        btn_refresh.clicked.connect(self.manual_refresh)
        btn_zero = QtWidgets.QPushButton("两板归零")
        btn_zero.clicked.connect(self.zero_all)
        btn_estop = QtWidgets.QPushButton("紧急停止")
        btn_estop.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        btn_estop.clicked.connect(self.estop_all)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(btn_refresh)
        button_row.addWidget(btn_zero)
        button_row.addWidget(btn_estop)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.urlLabel)
        layout.addWidget(self.infoLabel)
        layout.addWidget(QtWidgets.QLabel("剩余步数", alignment=QtCore.Qt.AlignmentFlag.AlignCenter))
        layout.addWidget(self.ackLabel)
        layout.addLayout(button_row)
        layout.addStretch()

        self.poller = StatusPoller(interval_ms=2000)
        self.poller.statusUpdated.connect(self.update_status)
        self.poller.errorRaised.connect(self.show_error)
        self.poller.start()

        self.manual_refresh()

    @QtCore.Slot()
    def manual_refresh(self) -> None:
        self.poller._poll()  # type: ignore[attr-defined]

    @QtCore.Slot()
    def zero_all(self) -> None:
        try:
            service.zero_all()
            QtWidgets.QMessageBox.information(self, "完成", "已发送归零命令。")
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))

    @QtCore.Slot()
    def estop_all(self) -> None:
        try:
            service.estop()
            QtWidgets.QMessageBox.warning(self, "紧急停止", "已发送紧急停止命令！")
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))

    @QtCore.Slot(dict)
    def update_status(self, snapshot: Dict[str, Any]) -> None:
        boards: List[Dict[str, Any]] = snapshot.get("boards", [])
        lines = []
        for item in boards:
            label = "主板" if item.get("index") == 0 else "副板"
            port = item.get("port") or "未连接"
            baud = item.get("baud")
            state = "运行" if item.get("is_open") else "空闲"
            lines.append(f"{label}: {port} @ {baud} ({state})")
        if not lines:
            lines.append("无串口连接")
        self.infoLabel.setText("\n".join(lines))

        ack = snapshot.get("ack", [])
        if ack:
            self.ackLabel.setText(" / ".join(f"P{i+1}:{v}" for i, v in enumerate(ack)))
        else:
            self.ackLabel.setText("--")

    @QtCore.Slot(str)
    def show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "错误", message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    host = get_preferred_ip()
    port = 8000

    runner = UvicornRunner(port=port)
    runner.start()
    time.sleep(0.5)  # allow server thread to start

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(host=host, port=port)
    window.show()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        runner.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


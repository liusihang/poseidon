#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend import Backend

APP_DIR = Path.home() / ".poseidon_touch"
APP_DIR.mkdir(parents=True, exist_ok=True)


def main():
    app = QGuiApplication([])
    engine = QQmlApplicationEngine()

    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)

    qml_root = Path(__file__).resolve().parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_root)))
    if not engine.rootObjects():
        raise SystemExit(1)

    app.exec()


if __name__ == "__main__":
    main()
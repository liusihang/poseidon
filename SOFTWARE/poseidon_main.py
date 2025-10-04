#!/usr/bin/env python
# -*- coding: utf-8 -*-

import serial
import time
import glob
import sys
from datetime import datetime
import time
import os
import json
from collections import defaultdict

# This gets the Qt stuff

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QMainWindow, QApplication, QFileDialog

import cv2

# note, had to use version 3.2.0.8 otherwise it had its own
# pyqt packages that conflicted with mine

import numpy as np
from decimal import Decimal

# This is our window from QtCreator
import poseidon_controller_gui
import pdb
import traceback, sys


# ##############################
# MULTITHREADING : SIGNALS CLASS
# ##############################
class WorkerSignals(QtCore.QObject):
    """
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
    No data

    error
    `tuple` (exctype, value, traceback.format_exc() )

    result
    `object` data returned from processing, anything

    """

    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(tuple)
    result = QtCore.pyqtSignal(object)
    progress = QtCore.pyqtSignal(int)


# #############################
# MULTITHREADING : WORKER CLASS
# #############################


class Thread(QtCore.QThread):
    def __init__(self, fn, *args, **kwargs):
        parent = None
        super(Thread, self).__init__(parent)
        self.runs = True
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            # self.serial.flushInput()
            # self.serial.flushOutput()
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()  # Done
            self.stop()

            print("Job completed")

    def stop(self):
        self.runs = False


# #####################################
# ERROR HANDLING : CANNOT CONNECT CLASS
# #####################################
class CannotConnectException(Exception):
    pass


class SyringeCalibrationDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, existing_names=None):
        super(SyringeCalibrationDialog, self).__init__(parent)
        self.setWindowTitle("Calibrate Syringe")
        self.setModal(True)
        self.calibration = None
        self.existing_names = set(existing_names or [])

        layout = QtWidgets.QVBoxLayout(self)

        instructions = QtWidgets.QLabel(
            "Measure how far the plunger travels for a known volume.\n"
            "Enter the syringe name, the test volume dispensed (mL), and the"
            " plunger displacement (mm)."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        form_layout = QtWidgets.QFormLayout()
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("e.g. Custom 5 mL")
        form_layout.addRow("Syringe name", self.name_input)

        self.volume_input = QtWidgets.QDoubleSpinBox()
        self.volume_input.setSuffix(" mL")
        self.volume_input.setDecimals(3)
        self.volume_input.setRange(0.001, 1000.0)
        self.volume_input.setValue(1.0)
        form_layout.addRow("Volume dispensed", self.volume_input)

        self.displacement_input = QtWidgets.QDoubleSpinBox()
        self.displacement_input.setSuffix(" mm")
        self.displacement_input.setDecimals(3)
        self.displacement_input.setRange(0.001, 1000.0)
        self.displacement_input.setValue(10.0)
        form_layout.addRow("Plunger travel", self.displacement_input)

        layout.addLayout(form_layout)

        self.error_label = QtWidgets.QLabel()
        palette = self.error_label.palette()
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("red"))
        self.error_label.setPalette(palette)
        layout.addWidget(self.error_label)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save
        )
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def validate_and_accept(self):
        name = self.name_input.text().strip()
        volume = self.volume_input.value()
        displacement = self.displacement_input.value()

        if not name:
            self.error_label.setText("Please provide a syringe name.")
            return
        if name in self.existing_names:
            self.error_label.setText("A syringe with this name already exists.")
            return
        if displacement <= 0:
            self.error_label.setText("Plunger travel must be greater than zero.")
            return

        area_mm2 = (volume * 1000.0) / displacement
        self.calibration = {
            "name": name,
            "volume_ml": volume,
            "area_mm2": area_mm2,
        }
        self.accept()

    def get_calibration(self):
        return self.calibration


# #######################
# GUI : MAIN WINDOW CLASS
# #######################
class MainWindow(QtWidgets.QMainWindow, poseidon_controller_gui.Ui_MainWindow):

    # =======================================================
    # INITIALIZING : The UI and setting some needed variables
    # =======================================================
    def __init__(self):

        # Setting the UI to a class variable and connecting all GUI Components
        super(MainWindow, self).__init__()
        self.ui = poseidon_controller_gui.Ui_MainWindow()
        self.ui.setupUi(self)

        self.serial_ports = {"primary": None, "secondary": None}
        self.selected_ports = {"primary": "", "secondary": ""}
        self.controller_labels = {
            "primary": "CNC Shield A",
            "secondary": "CNC Shield B",
        }
        self.pump_to_controller = {
            1: "primary",
            2: "primary",
            3: "secondary",
            4: "secondary",
        }
        self.calibration_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "calibrations.json"
        )
        self.custom_syringes = []
        self.available_ports = []

        # Put comments here
        self.populate_microstepping()
        self.populate_syringe_sizes()
        self.populate_pump_jog_delta()
        self.populate_pump_units()
        self.setting_variables()
        self.populate_ports()
        self.set_primary_port()
        self.set_secondary_port()

        self.connect_all_gui_components()
        self.grey_out_components()

        # Declaring start, mid, and end marker for sending code to Arduino
        self.startMarker = 60  # <
        self.endMarker = 62  # ,F,0.0>
        self.midMarker = 44  # ,

        # Initializing multithreading to allow parallel operations
        self.threadpool = QtCore.QThreadPool()
        print(
            "Multithreading with maximum %d threads" % self.threadpool.maxThreadCount()
        )

        # Camera setup
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.recurring_timer)
        self.timer.start()
        self.counter = 0

        # Random other things I need
        self.image = None
        # self.microstepping = 1
        # print(self.microstepping)

    def recurring_timer(self):
        self.counter += 1

    # =============================
    # SETTING : important variables
    # =============================
    def setting_variables(self):

        self.set_p1_syringe()
        self.set_p2_syringe()
        self.set_p3_syringe()
        self.set_p4_syringe()

        # self.set_p1_units()
        # self.set_p2_units()
        # self.set_p3_units()

        self.is_p1_active = False
        self.is_p2_active = False
        self.is_p3_active = False
        self.is_p4_active = False

        self.experiment_notes = ""

    def thread_finished(self, th):
        print("Your thread has completed. Now terminating..")
        th.stop()
        print("Thread has been terminated.")
        print("=============================\n\n")
        # here is where you need to end the thread

    # ===================================
    # CONNECTING : all the GUI Components
    # ===================================
    def connect_all_gui_components(self):

        # ~~~~~~~~~~~~~~~
        # MAIN : MENU BAR
        # ~~~~~~~~~~~~~~~
        self.ui.load_settings_BTN.triggered.connect(self.load_settings)
        self.ui.save_settings_BTN.triggered.connect(self.save_settings)

        # ~~~~~~~~~~~~~~~~
        # TAB : Controller
        # ~~~~~~~~~~~~~~~~

        # Px active checkboxes
        self.ui.p1_activate_CHECKBOX.stateChanged.connect(self.toggle_p1_activation)
        self.ui.p2_activate_CHECKBOX.stateChanged.connect(self.toggle_p2_activation)
        self.ui.p3_activate_CHECKBOX.stateChanged.connect(self.toggle_p3_activation)
        self.ui.p4_activate_CHECKBOX.stateChanged.connect(self.toggle_p4_activation)

        # Px display (TODO)

        # Px syringe display
        self.ui.p1_syringe_DROPDOWN.currentIndexChanged.connect(self.display_p1_syringe)
        self.ui.p2_syringe_DROPDOWN.currentIndexChanged.connect(self.display_p2_syringe)
        self.ui.p3_syringe_DROPDOWN.currentIndexChanged.connect(self.display_p3_syringe)
        self.ui.p4_syringe_DROPDOWN.currentIndexChanged.connect(self.display_p4_syringe)

        # Px speed display
        self.ui.p1_units_DROPDOWN.currentIndexChanged.connect(self.display_p1_speed)
        self.ui.p2_units_DROPDOWN.currentIndexChanged.connect(self.display_p2_speed)
        self.ui.p3_units_DROPDOWN.currentIndexChanged.connect(self.display_p3_speed)
        self.ui.p4_units_DROPDOWN.currentIndexChanged.connect(self.display_p4_speed)

        # self.populate_pump_units()

        # Px amount
        self.ui.p1_amount_INPUT.valueChanged.connect(self.set_p1_amount)
        self.ui.p2_amount_INPUT.valueChanged.connect(self.set_p2_amount)
        self.ui.p3_amount_INPUT.valueChanged.connect(self.set_p3_amount)
        self.ui.p4_amount_INPUT.valueChanged.connect(self.set_p4_amount)

        # Px jog delta
        # self.ui.p1_jog_delta_INPUT.valueChanged.connect(self.set_p1_jog_delta)
        # self.ui.p2_jog_delta_INPUT.valueChanged.connect(self.set_p2_jog_delta)
        # self.ui.p3_jog_delta_INPUT.valueChanged.connect(self.set_p3_jog_delta)

        # Action buttons
        self.ui.run_BTN.clicked.connect(self.run)

        self.ui.pause_BTN.clicked.connect(self.pause)

        self.ui.zero_BTN.clicked.connect(self.zero)
        self.ui.stop_BTN.clicked.connect(self.stop)

        self.ui.jog_plus_BTN.clicked.connect(lambda: self.jog(self.ui.jog_plus_BTN))
        self.ui.jog_minus_BTN.clicked.connect(lambda: self.jog(self.ui.jog_minus_BTN))

        # Set coordinate system
        self.ui.absolute_RADIO.toggled.connect(
            lambda: self.set_coordinate(self.ui.absolute_RADIO)
        )
        self.ui.incremental_RADIO.toggled.connect(
            lambda: self.set_coordinate(self.ui.incremental_RADIO)
        )

        # ~~~~~~~~~~~
        # TAB : Setup
        # ~~~~~~~~~~~

        # Port, first populate it then connect it (population done earlier)
        self.ui.refresh_ports_BTN.clicked.connect(self.refresh_ports)
        self.ui.primary_port_DROPDOWN.currentIndexChanged.connect(self.set_primary_port)
        self.ui.secondary_port_DROPDOWN.currentIndexChanged.connect(
            self.set_secondary_port
        )
        self.ui.primary_connect_BTN.clicked.connect(
            lambda: self.connect_controller("primary")
        )
        self.ui.primary_disconnect_BTN.clicked.connect(
            lambda: self.disconnect_controller("primary")
        )
        self.ui.secondary_connect_BTN.clicked.connect(
            lambda: self.connect_controller("secondary")
        )
        self.ui.secondary_disconnect_BTN.clicked.connect(
            lambda: self.disconnect_controller("secondary")
        )

        self.ui.experiment_notes.editingFinished.connect(self.set_experiment_notes)

        # Set the microstepping value, default is 1
        self.ui.microstepping_DROPDOWN.currentIndexChanged.connect(
            self.set_microstepping
        )
        self.ui.calibrate_syringe_BTN.clicked.connect(self.open_calibration_dialog)

        # Set the log file name
        self.date_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.date_string = self.date_string.replace(
            ":", "_"
        )  # Replace semicolons with underscores

        # Px syringe size, populate then connect (population done earlier)
        self.ui.p1_syringe_DROPDOWN.currentIndexChanged.connect(self.set_p1_syringe)
        self.ui.p2_syringe_DROPDOWN.currentIndexChanged.connect(self.set_p2_syringe)
        self.ui.p3_syringe_DROPDOWN.currentIndexChanged.connect(self.set_p3_syringe)
        self.ui.p4_syringe_DROPDOWN.currentIndexChanged.connect(self.set_p4_syringe)
        # warning to send the info to the controller
        self.ui.p1_syringe_DROPDOWN.currentIndexChanged.connect(self.send_p1_warning)
        self.ui.p2_syringe_DROPDOWN.currentIndexChanged.connect(self.send_p2_warning)
        self.ui.p3_syringe_DROPDOWN.currentIndexChanged.connect(self.send_p3_warning)
        self.ui.p4_syringe_DROPDOWN.currentIndexChanged.connect(self.send_p4_warning)

        # Px units
        self.ui.p1_units_DROPDOWN.currentIndexChanged.connect(self.set_p1_units)
        self.ui.p2_units_DROPDOWN.currentIndexChanged.connect(self.set_p2_units)
        self.ui.p3_units_DROPDOWN.currentIndexChanged.connect(self.set_p3_units)
        self.ui.p4_units_DROPDOWN.currentIndexChanged.connect(self.set_p4_units)
        # warning to send the info to the controller
        self.ui.p1_units_DROPDOWN.currentIndexChanged.connect(self.send_p1_warning)
        self.ui.p2_units_DROPDOWN.currentIndexChanged.connect(self.send_p2_warning)
        self.ui.p3_units_DROPDOWN.currentIndexChanged.connect(self.send_p3_warning)
        self.ui.p4_units_DROPDOWN.currentIndexChanged.connect(self.send_p4_warning)

        # Px speed
        self.ui.p1_speed_INPUT.valueChanged.connect(self.set_p1_speed)
        self.ui.p2_speed_INPUT.valueChanged.connect(self.set_p2_speed)
        self.ui.p3_speed_INPUT.valueChanged.connect(self.set_p3_speed)
        self.ui.p4_speed_INPUT.valueChanged.connect(self.set_p4_speed)
        # warning to send the info to the controller
        self.ui.p1_speed_INPUT.valueChanged.connect(self.send_p1_warning)
        self.ui.p2_speed_INPUT.valueChanged.connect(self.send_p2_warning)
        self.ui.p3_speed_INPUT.valueChanged.connect(self.send_p3_warning)
        self.ui.p4_speed_INPUT.valueChanged.connect(self.send_p4_warning)

        # Px accel
        self.ui.p1_accel_INPUT.valueChanged.connect(self.set_p1_accel)
        self.ui.p2_accel_INPUT.valueChanged.connect(self.set_p2_accel)
        self.ui.p3_accel_INPUT.valueChanged.connect(self.set_p3_accel)
        self.ui.p4_accel_INPUT.valueChanged.connect(self.set_p4_accel)
        # warning to send the info to the controller
        self.ui.p1_accel_INPUT.valueChanged.connect(self.send_p1_warning)
        self.ui.p2_accel_INPUT.valueChanged.connect(self.send_p2_warning)
        self.ui.p3_accel_INPUT.valueChanged.connect(self.send_p3_warning)
        self.ui.p4_accel_INPUT.valueChanged.connect(self.send_p4_warning)

        # Px jog delta (setup)
        self.ui.p1_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.set_p1_setup_jog_delta
        )
        self.ui.p2_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.set_p2_setup_jog_delta
        )
        self.ui.p3_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.set_p3_setup_jog_delta
        )
        self.ui.p4_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.set_p4_setup_jog_delta
        )
        # warning to send the info to the contorller
        self.ui.p1_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.send_p1_warning
        )
        self.ui.p2_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.send_p2_warning
        )
        self.ui.p3_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.send_p3_warning
        )
        self.ui.p4_setup_jog_delta_INPUT.currentIndexChanged.connect(
            self.send_p4_warning
        )

        # Px send settings
        self.ui.p1_setup_send_BTN.clicked.connect(self.send_p1_settings)
        self.ui.p2_setup_send_BTN.clicked.connect(self.send_p2_settings)
        self.ui.p3_setup_send_BTN.clicked.connect(self.send_p3_settings)
        self.ui.p4_setup_send_BTN.clicked.connect(self.send_p4_settings)
        # remove warning to send settings
        self.ui.p1_setup_send_BTN.clicked.connect(self.send_p1_success)
        self.ui.p2_setup_send_BTN.clicked.connect(self.send_p2_success)
        self.ui.p3_setup_send_BTN.clicked.connect(self.send_p3_success)
        self.ui.p4_setup_send_BTN.clicked.connect(self.send_p4_success)

        # Send all the settings at once
        self.ui.send_all_BTN.clicked.connect(self.send_all)

    def send_p1_warning(self):
        self.ui.p1_setup_send_BTN.setStyleSheet("background-color: green; color: black")

    def send_p2_warning(self):
        self.ui.p2_setup_send_BTN.setStyleSheet("background-color: green; color: black")

    def send_p3_warning(self):
        self.ui.p3_setup_send_BTN.setStyleSheet("background-color: green; color: black")

    def send_p4_warning(self):
        self.ui.p4_setup_send_BTN.setStyleSheet("background-color: green; color: black")

    def send_p1_success(self):
        self.ui.p1_setup_send_BTN.setStyleSheet("background-color: none")

    def send_p2_success(self):
        self.ui.p2_setup_send_BTN.setStyleSheet("background-color: none")

    def send_p3_success(self):
        self.ui.p3_setup_send_BTN.setStyleSheet("background-color: none")

    def send_p4_success(self):
        self.ui.p4_setup_send_BTN.setStyleSheet("background-color: none")

    def grey_out_components(self):
        for pump_id in range(1, 5):
            getattr(self.ui, f"p{pump_id}_setup_send_BTN").setStyleSheet(
                "background-color: none"
            )
        self.update_component_states()

    def ungrey_out_components(self):
        self.update_component_states()

    # ======================
    # FUNCTIONS : Controller
    # ======================

    def toggle_p1_activation(self):
        if self.ui.p1_activate_CHECKBOX.isChecked():
            self.is_p1_active = True
        else:
            self.is_p1_active = False

    def toggle_p2_activation(self):
        if self.ui.p2_activate_CHECKBOX.isChecked():
            self.is_p2_active = True
        else:
            self.is_p2_active = False

    def toggle_p3_activation(self):
        if self.ui.p3_activate_CHECKBOX.isChecked():
            self.is_p3_active = True
        else:
            self.is_p3_active = False

    def toggle_p4_activation(self):
        if self.ui.p4_activate_CHECKBOX.isChecked():
            self.is_p4_active = True
        else:
            self.is_p4_active = False

    # Get a list of active pumps (IDK if this is the best way to do this)
    def get_active_pumps(self):
        pumps_list = [
            self.is_p1_active,
            self.is_p2_active,
            self.is_p3_active,
            self.is_p4_active,
        ]
        active_pumps = []
        for idx, active in enumerate(pumps_list, start=1):
            if not active:
                continue
            controller_id = self.pump_to_controller.get(idx)
            if controller_id and self.serial_ports.get(controller_id):
                active_pumps.append(idx)
        return active_pumps

    def display_p1_syringe(self):
        self.ui.p1_syringe_LABEL.setText(self.ui.p1_syringe_DROPDOWN.currentText())

    def display_p2_syringe(self):
        self.ui.p2_syringe_LABEL.setText(self.ui.p2_syringe_DROPDOWN.currentText())

    def display_p3_syringe(self):
        self.ui.p3_syringe_LABEL.setText(self.ui.p3_syringe_DROPDOWN.currentText())

    def display_p4_syringe(self):
        self.ui.p4_syringe_LABEL.setText(self.ui.p4_syringe_DROPDOWN.currentText())

    def display_p1_speed(self):
        self.ui.p1_units_LABEL.setText(
            str(self.p1_speed) + " " + self.ui.p1_units_DROPDOWN.currentText()
        )

    def display_p2_speed(self):
        self.ui.p2_units_LABEL.setText(
            str(self.p2_speed) + " " + self.ui.p2_units_DROPDOWN.currentText()
        )

    def display_p3_speed(self):
        self.ui.p3_units_LABEL.setText(
            str(self.p3_speed) + " " + self.ui.p3_units_DROPDOWN.currentText()
        )

    def display_p4_speed(self):
        self.ui.p4_units_LABEL.setText(
            str(self.p4_speed) + " " + self.ui.p4_units_DROPDOWN.currentText()
        )

    # Set Px distance to move
    def set_p1_amount(self):
        self.p1_amount = self.ui.p1_amount_INPUT.value()

    def set_p2_amount(self):
        self.p2_amount = self.ui.p2_amount_INPUT.value()

    def set_p3_amount(self):
        self.p3_amount = self.ui.p3_amount_INPUT.value()

    def set_p4_amount(self):
        self.p4_amount = self.ui.p4_amount_INPUT.value()

    # Set Px jog delta
    # def set_p1_jog_delta(self):
    #    self.p1_jog_delta = self.ui.p1_jog_delta_INPUT.value()
    # def set_p2_jog_delta(self):
    #    self.p2_jog_delta = self.ui.p2_jog_delta_INPUT.value()
    # def set_p3_jog_delta(self):
    #    self.p3_jog_delta = self.ui.p3_jog_delta_INPUT.value()

    # Set the coordinate system for the pump
    def set_coordinate(self, radio):
        if radio.text() == "Abs.":
            if radio.isChecked():
                self.coordinate = "absolute"
        if radio.text() == "Incr.":
            if radio.isChecked():
                self.coordinate = "incremental"

    def run(self):
        self.statusBar().showMessage("You clicked RUN")
        active_pumps = self.get_active_pumps()
        if not active_pumps:
            self.statusBar().showMessage("No pumps enabled.")
            return
        p1_input_displacement = str(
            self.convert_displacement(
                self.p1_amount, self.p1_units, self.p1_syringe_area, self.microstepping
            )
        )
        p2_input_displacement = str(
            self.convert_displacement(
                self.p2_amount, self.p2_units, self.p2_syringe_area, self.microstepping
            )
        )
        p3_input_displacement = str(
            self.convert_displacement(
                self.p3_amount, self.p3_units, self.p3_syringe_area, self.microstepping
            )
        )
        p4_input_displacement = str(
            self.convert_displacement(
                self.p4_amount, self.p4_units, self.p4_syringe_area, self.microstepping
            )
        )
        displacements = [
            p1_input_displacement,
            p2_input_displacement,
            p3_input_displacement,
            p4_input_displacement,
        ]
        controller_commands = []
        for controller_id in self.serial_ports:
            controller_pumps = [
                pump
                for pump in active_pumps
                if self.pump_to_controller.get(pump) == controller_id
            ]
            if not controller_pumps:
                continue
            pumps_to_run = "".join(str(pump) for pump in controller_pumps)
            payload = displacements.copy()
            for idx in range(1, 5):
                if idx not in controller_pumps:
                    payload[idx - 1] = "0.0"
            command = f"<RUN,DIST,{pumps_to_run},0.0,F,{','.join(payload)}>"
            controller_commands.append((controller_id, command))
        if controller_commands:
            print("Sending RUN command..")
            self.dispatch_commands(controller_commands)
            print("RUN command sent.")
        else:
            self.statusBar().showMessage("No connected controllers for selected pumps.")

    def pause(self):
        active_pumps = self.get_active_pumps()
        if not active_pumps:
            self.statusBar().showMessage("No pumps enabled.")
            return

        if self.ui.pause_BTN.text() == "Pause":
            self.statusBar().showMessage("You clicked PAUSE")
            controller_commands = []
            for controller_id in self.serial_ports:
                controller_pumps = [
                    pump
                    for pump in active_pumps
                    if self.pump_to_controller.get(pump) == controller_id
                ]
                if not controller_pumps:
                    continue
                pumps = "".join(str(pump) for pump in controller_pumps)
                cmd = f"<PAUSE,BLAH,{pumps},BLAH,F,0.0,0.0,0.0,0.0>"
                controller_commands.append((controller_id, cmd))

            if controller_commands:
                print("Sending PAUSE command..")
                self.dispatch_commands(controller_commands)
                print("PAUSE command sent.")

            self.ui.pause_BTN.setText("Resume")

        elif self.ui.pause_BTN.text() == "Resume":
            self.statusBar().showMessage("You clicked RESUME")
            controller_commands = []
            for controller_id in self.serial_ports:
                controller_pumps = [
                    pump
                    for pump in active_pumps
                    if self.pump_to_controller.get(pump) == controller_id
                ]
                if not controller_pumps:
                    continue
                pumps = "".join(str(pump) for pump in controller_pumps)
                cmd = f"<RESUME,BLAH,{pumps},BLAH,F,0.0,0.0,0.0,0.0>"
                controller_commands.append((controller_id, cmd))

            if controller_commands:
                print("Sending RESUME command..")
                self.dispatch_commands(controller_commands)
                print("RESUME command sent.")

            self.ui.pause_BTN.setText("Pause")

    # fix
    def zero(self):
        self.statusBar().showMessage("You clicked ZERO")
        controller_commands = []
        for controller_id in self.serial_ports:
            if self.serial_ports.get(controller_id):
                controller_commands.append(
                    (controller_id, "<ZERO,BLAH,BLAH,BLAH,F,0.0,0.0,0.0,0.0>")
                )

        if controller_commands:
            print("Sending ZERO command..")
            self.dispatch_commands(controller_commands)
            print("ZERO command sent.")
        else:
            self.statusBar().showMessage("No controllers connected.")

    def stop(self):
        self.statusBar().showMessage("You clicked STOP")
        controller_commands = []
        for controller_id in self.serial_ports:
            if self.serial_ports.get(controller_id):
                controller_commands.append(
                    (controller_id, "<STOP,BLAH,BLAH,BLAH,F,0.0,0.0,0.0,0.0>")
                )

        if controller_commands:
            print("Sending STOP command..")
            self.dispatch_commands(controller_commands)
            print("STOP command sent.")
        else:
            self.statusBar().showMessage("No controllers connected.")

    def jog(self, btn):
        self.statusBar().showMessage("You clicked JOG")
        active_pumps = self.get_active_pumps()
        if not active_pumps:
            self.statusBar().showMessage("No pumps enabled.")
            return

        payload = [
            str(self.p1_setup_jog_delta_to_send),
            str(self.p2_setup_jog_delta_to_send),
            str(self.p3_setup_jog_delta_to_send),
            str(self.p4_setup_jog_delta_to_send),
        ]

        forward = btn.text() == "Jog +"
        direction_flag = "F" if forward else "B"
        self.statusBar().showMessage(
            "You clicked JOG +" if forward else "You clicked JOG -"
        )

        controller_commands = []
        for controller_id in self.serial_ports:
            controller_pumps = [
                pump
                for pump in active_pumps
                if self.pump_to_controller.get(pump) == controller_id
            ]
            if not controller_pumps:
                continue
            pumps = "".join(str(pump) for pump in controller_pumps)
            controller_payload = payload.copy()
            for idx in range(1, 5):
                if idx not in controller_pumps:
                    controller_payload[idx - 1] = "0.0"
            cmd = (
                f"<RUN,DIST,{pumps},0,{direction_flag},{','.join(controller_payload)}>"
            )
            controller_commands.append((controller_id, cmd))

        if controller_commands:
            print("Sending JOG command..")
            self.dispatch_commands(controller_commands)
            print("JOG command sent.")

    # ======================
    # FUNCTIONS : Camera
    # ======================

    # Initialize the camera
    def start_camera(self):
        self.statusBar().showMessage("You clicked START CAMERA")
        camera_port = 0
        self.capture = cv2.VideoCapture(camera_port)
        # TODO check the native resolution of the camera and scale the size down here
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 800)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 400)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(5)

    # Update frame function
    def update_frame(self):
        ret, self.image = self.capture.read()
        self.image = cv2.flip(self.image, 1)
        self.display_image(self.image, 1)

    # Display image in frame
    def display_image(self, image, window=1):
        qformat = QtGui.QImage.Format_Indexed8
        if len(image.shape) == 3:  #
            if image.shape[2] == 4:
                qformat = QtGui.QImage.Format_RGBA8888

            else:
                qformat = QtGui.QImage.Format_RGB888
                # print(image.shape[0], image.shape[1], image.shape[2])
        self.img_2_display = QtGui.QImage(
            image, image.shape[1], image.shape[0], image.strides[0], qformat
        )
        self.img_2_display = QtGui.QImage.rgbSwapped(self.img_2_display)

        if window == 1:
            self.ui.imgLabel.setPixmap(QtGui.QPixmap.fromImage(self.img_2_display))
            self.ui.imgLabel.setScaledContents(False)

    # Save image to set location
    def save_image(self):
        if not os.path.exists("./images"):
            os.mkdir("images")

        self.date_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Replace semicolons with underscores
        self.date_string = self.date_string.replace(":", "_")
        self.write_image_loc = "./images/" + self.date_string + ".png"
        cv2.imwrite(self.write_image_loc, self.image)
        self.statusBar().showMessage(
            "Captured Image, saved to: " + self.write_image_loc
        )

    # Stop camera
    def stop_camera(self):
        self.timer.stop()

    # ======================
    # FUNCTIONS : Setup
    # ======================

    # Populate the available ports
    def populate_ports(self):
        """
        Populate both controller port selectors with available serial ports.
        """
        print("Populating ports..")
        if sys.platform.startswith("win"):
            ports = ["COM%s" % (i + 1) for i in range(256)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            ports = glob.glob("/dev/tty[A-Za-z]*")
        elif sys.platform.startswith("darwin"):
            ports = glob.glob("/dev/tty.*")
        else:
            raise EnvironmentError("Unsupported platform")

        result = []
        for port in ports:
            try:
                s = serial.Serial(port)
                s.close()
                result.append(port)
            except (OSError, serial.SerialException):
                pass

        self.available_ports = result
        self.ui.primary_port_DROPDOWN.clear()
        self.ui.secondary_port_DROPDOWN.clear()
        self.ui.primary_port_DROPDOWN.addItems(result)
        self.ui.secondary_port_DROPDOWN.addItems(result)
        print("Ports have been populated.")

    # Refresh the list of ports
    def refresh_ports(self):
        self.statusBar().showMessage("Refreshing ports")
        previous_primary = self.selected_ports.get("primary", "")
        previous_secondary = self.selected_ports.get("secondary", "")
        self.populate_ports()

        if previous_primary in self.available_ports:
            index = self.ui.primary_port_DROPDOWN.findText(
                previous_primary, QtCore.Qt.MatchFixedString
            )
            self.ui.primary_port_DROPDOWN.setCurrentIndex(index)
        else:
            self.ui.primary_port_DROPDOWN.setCurrentIndex(
                0 if self.available_ports else -1
            )

        if previous_secondary in self.available_ports:
            index = self.ui.secondary_port_DROPDOWN.findText(
                previous_secondary, QtCore.Qt.MatchFixedString
            )
            self.ui.secondary_port_DROPDOWN.setCurrentIndex(index)
        else:
            self.ui.secondary_port_DROPDOWN.setCurrentIndex(
                0 if self.available_ports else -1
            )

        self.set_primary_port()
        self.set_secondary_port()

    def set_primary_port(self):
        self.selected_ports["primary"] = self.ui.primary_port_DROPDOWN.currentText()
        if self.serial_ports.get("primary"):
            self.update_connection_ui("primary", True)

    def set_secondary_port(self):
        self.selected_ports["secondary"] = self.ui.secondary_port_DROPDOWN.currentText()
        if self.serial_ports.get("secondary"):
            self.update_connection_ui("secondary", True)

    # Set the microstepping amount from the dropdown menu
    # TODO: There is definitely a better way of updating different variables
    # after there is a change of some input from the user. need to figure out.
    def set_microstepping(self):
        self.microstepping = int(self.ui.microstepping_DROPDOWN.currentText())
        self.set_p1_units()
        self.set_p1_speed()
        self.set_p1_accel()
        self.set_p1_setup_jog_delta()
        self.set_p1_amount()

        self.set_p2_units()
        self.set_p2_speed()
        self.set_p2_accel()
        self.set_p2_setup_jog_delta()
        self.set_p2_amount()

        self.set_p3_units()
        self.set_p3_speed()
        self.set_p3_accel()
        self.set_p3_setup_jog_delta()
        self.set_p3_amount()

        self.set_p4_units()
        self.set_p4_speed()
        self.set_p4_accel()
        self.set_p4_setup_jog_delta()
        self.set_p4_amount()

        print(self.microstepping)

    def set_experiment_notes(self):
        self.experiment_notes = self.ui.experiment_notes.text()

    # Set the name of the log file
    # Can probably delete
    def set_log_file_name(self):
        """
        Sets the file name for the current test run, enables us to log data to the file.

        Callback setter method from the 'self.ui.logFileNameInput' to set the
        name of the log file. The log file name is of the form
        label_Year-Month-Date hour_min_sec.txt
        """
        # Create a date string
        self.date_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Replace semicolons with underscores
        self.date_string = self.date_string.replace(":", "_")
        self.log_file_name = (
            self.ui.log_file_name_INPUT.text() + "_" + self.date_string + ".png"
        )

    def save_settings(self):
        name, _ = QFileDialog.getSaveFileName(
            self,
            "Save File",
            options=QFileDialog.DontUseNativeDialog,
            filter="Text (*.txt)",
        )

        if not name:
            self.statusBar().showMessage("No file selected.")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        pump_settings = []
        for pump_id in range(1, 5):
            pump_settings.append(
                {
                    "label": f"P{pump_id}",
                    "syringe": getattr(self, f"p{pump_id}_syringe", ""),
                    "units": getattr(self, f"p{pump_id}_units", ""),
                    "speed": getattr(self, f"p{pump_id}_speed", ""),
                    "accel": getattr(self, f"p{pump_id}_accel", ""),
                    "jog": getattr(self, f"p{pump_id}_setup_jog_delta", ""),
                }
            )

        experiment_notes = self.experiment_notes

        primary_port = self.selected_ports.get("primary", "")
        secondary_port = self.selected_ports.get("secondary", "")
        primary_connected = bool(self.serial_ports.get("primary"))
        secondary_connected = bool(self.serial_ports.get("secondary"))

        lines = []
        lines.append(f"File name: {os.path.basename(name)}\n")
        lines.append(f"Date time: {timestamp}\n")
        lines.append(f"Primary Port: {primary_port}\n")
        lines.append(f"Primary Connected: {primary_connected}\n")
        lines.append(f"Secondary Port: {secondary_port}\n")
        lines.append(f"Secondary Connected: {secondary_connected}\n")
        lines.append(":================================ \n")

        for pump in pump_settings:
            lines.append(f"{pump['label']} Syrin: {pump['syringe']}\n")
            lines.append(f"{pump['label']} Units: {pump['units']}\n")
            lines.append(f"{pump['label']} Speed: {pump['speed']}\n")
            lines.append(f"{pump['label']} Accel: {pump['accel']}\n")
            lines.append(f"{pump['label']} Jog D: {pump['jog']}\n")
            lines.append(":================================ \n")

        lines.append(f"Exp Note: {experiment_notes}")

        if not name.lower().endswith(".txt"):
            name = f"{name}.txt"

        with open(name, "w") as fh:
            fh.writelines(lines)

        self.statusBar().showMessage(f"Settings saved in {os.path.basename(name)}")

    def load_settings(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Open File",
            options=QFileDialog.DontUseNativeDialog,
            filter="Text (*.txt)",
        )

        if not name:
            self.statusBar().showMessage("No file selected.")
            return

        settings_map = {}
        with open(name, "r") as f:
            for raw_line in f:
                if ":" not in raw_line:
                    continue
                key, value = raw_line.split(":", 1)
                key = key.strip()
                if not key:
                    continue
                settings_map[key] = value.strip()

        def apply_dropdown(dropdown, value):
            if value is None:
                return
            index = dropdown.findText(value, QtCore.Qt.MatchFixedString)
            if index != -1:
                dropdown.setCurrentIndex(index)

        primary_port = settings_map.get("Primary Port", "")
        if primary_port:
            apply_dropdown(self.ui.primary_port_DROPDOWN, primary_port)
            self.set_primary_port()

        secondary_port = settings_map.get("Secondary Port", "")
        if secondary_port:
            apply_dropdown(self.ui.secondary_port_DROPDOWN, secondary_port)
            self.set_secondary_port()

        apply_dropdown(self.ui.p1_syringe_DROPDOWN, settings_map.get("P1 Syrin"))
        apply_dropdown(self.ui.p2_syringe_DROPDOWN, settings_map.get("P2 Syrin"))
        apply_dropdown(self.ui.p3_syringe_DROPDOWN, settings_map.get("P3 Syrin"))
        apply_dropdown(self.ui.p4_syringe_DROPDOWN, settings_map.get("P4 Syrin"))

        apply_dropdown(self.ui.p1_units_DROPDOWN, settings_map.get("P1 Units"))
        apply_dropdown(self.ui.p2_units_DROPDOWN, settings_map.get("P2 Units"))
        apply_dropdown(self.ui.p3_units_DROPDOWN, settings_map.get("P3 Units"))
        apply_dropdown(self.ui.p4_units_DROPDOWN, settings_map.get("P4 Units"))

        apply_dropdown(self.ui.p1_setup_jog_delta_INPUT, settings_map.get("P1 Jog D"))
        apply_dropdown(self.ui.p2_setup_jog_delta_INPUT, settings_map.get("P2 Jog D"))
        apply_dropdown(self.ui.p3_setup_jog_delta_INPUT, settings_map.get("P3 Jog D"))
        apply_dropdown(self.ui.p4_setup_jog_delta_INPUT, settings_map.get("P4 Jog D"))

        def apply_float(spin_box, key):
            value = settings_map.get(key)
            if value is None:
                return
            try:
                spin_box.setValue(float(value))
            except ValueError:
                pass

        apply_float(self.ui.p1_speed_INPUT, "P1 Speed")
        apply_float(self.ui.p2_speed_INPUT, "P2 Speed")
        apply_float(self.ui.p3_speed_INPUT, "P3 Speed")
        apply_float(self.ui.p4_speed_INPUT, "P4 Speed")

        apply_float(self.ui.p1_accel_INPUT, "P1 Accel")
        apply_float(self.ui.p2_accel_INPUT, "P2 Accel")
        apply_float(self.ui.p3_accel_INPUT, "P3 Accel")
        apply_float(self.ui.p4_accel_INPUT, "P4 Accel")

        experiment_notes = settings_map.get("Exp Note")
        if experiment_notes is not None:
            self.ui.experiment_notes.setText(experiment_notes)

        loaded_time = settings_map.get("Date time", "")
        self.statusBar().showMessage(f"Settings loaded from: {loaded_time}")

    # Populate the microstepping amounts for the dropdown menu
    def populate_microstepping(self):
        self.microstepping_values = ["1", "2", "4", "8", "16", "32"]
        self.ui.microstepping_DROPDOWN.addItems(self.microstepping_values)
        self.microstepping = 1

    # Populate the list of possible syringes to the dropdown menus
    def populate_syringe_sizes(self):
        self.default_syringes = [
            {
                "name": "BD 1 mL",
                "volume_ml": 1,
                "area_mm2": 17.34206347,
                "custom": False,
            },
            {
                "name": "BD 3 mL",
                "volume_ml": 3,
                "area_mm2": 57.88559215,
                "custom": False,
            },
            {
                "name": "BD 5 mL",
                "volume_ml": 5,
                "area_mm2": 112.9089185,
                "custom": False,
            },
            {
                "name": "BD 10 mL",
                "volume_ml": 10,
                "area_mm2": 163.539454,
                "custom": False,
            },
            {
                "name": "BD 20 mL",
                "volume_ml": 20,
                "area_mm2": 285.022957,
                "custom": False,
            },
            {
                "name": "BD 30 mL",
                "volume_ml": 30,
                "area_mm2": 366.0961536,
                "custom": False,
            },
            {
                "name": "BD 60 mL",
                "volume_ml": 60,
                "area_mm2": 554.0462538,
                "custom": False,
            },
        ]
        self.load_calibration_data()
        self.refresh_syringe_dropdowns(initial=True)

    def load_calibration_data(self):
        if os.path.exists(self.calibration_path):
            try:
                with open(self.calibration_path, "r") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                data = []
        else:
            data = []

        self.custom_syringes = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            area = entry.get("area_mm2")
            volume = entry.get("volume_ml", 0)
            if name and isinstance(area, (int, float)):
                self.custom_syringes.append(
                    {
                        "name": name,
                        "volume_ml": volume,
                        "area_mm2": area,
                        "custom": True,
                    }
                )

    def save_calibration_data(self):
        data = [
            {
                "name": item["name"],
                "volume_ml": item.get("volume_ml", 0),
                "area_mm2": item["area_mm2"],
            }
            for item in self.custom_syringes
        ]
        try:
            with open(self.calibration_path, "w") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            self.statusBar().showMessage("Unable to write calibration file.")

    def refresh_syringe_dropdowns(self, initial=False):
        current_selection = {}
        if not initial:
            for pump_id in range(1, 5):
                dropdown = getattr(self.ui, f"p{pump_id}_syringe_DROPDOWN")
                current_selection[pump_id] = dropdown.currentText()

        catalog = self.default_syringes + self.custom_syringes
        self.syringe_options = []
        self.syringe_area_lookup = {}

        for entry in catalog:
            display_name = entry["name"]
            if entry.get("custom"):
                display_name = f"{display_name} (Calibrated)"
            self.syringe_options.append(display_name)
            self.syringe_area_lookup[display_name] = entry["area_mm2"]

        for pump_id in range(1, 5):
            dropdown = getattr(self.ui, f"p{pump_id}_syringe_DROPDOWN")
            dropdown.blockSignals(True)
            dropdown.clear()
            dropdown.addItems(self.syringe_options)
            dropdown.blockSignals(False)

        for pump_id in range(1, 5):
            dropdown = getattr(self.ui, f"p{pump_id}_syringe_DROPDOWN")
            target_text = current_selection.get(pump_id)
            if target_text in self.syringe_options:
                dropdown.setCurrentText(target_text)
            elif self.syringe_options:
                dropdown.setCurrentIndex(0)

        self.set_p1_syringe()
        self.set_p2_syringe()
        self.set_p3_syringe()
        self.set_p4_syringe()

    def open_calibration_dialog(self):
        existing_names = [entry["name"] for entry in self.default_syringes] + [
            entry["name"] for entry in self.custom_syringes
        ]
        dialog = SyringeCalibrationDialog(self, existing_names=existing_names)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            calibration = dialog.get_calibration()
            if calibration:
                calibration["custom"] = True
                self.custom_syringes.append(calibration)
                self.save_calibration_data()
                self.refresh_syringe_dropdowns()
                display_name = f"{calibration['name']} (Calibrated)"
                for pump_id in range(1, 5):
                    dropdown = getattr(self.ui, f"p{pump_id}_syringe_DROPDOWN")
                    index = dropdown.findText(display_name, QtCore.Qt.MatchFixedString)
                    if index != -1:
                        dropdown.setCurrentIndex(index)
                self.statusBar().showMessage(
                    f"Saved calibration for {calibration['name']}."
                )

    # Set Px syringe
    def set_p1_syringe(self):
        self.p1_syringe = self.ui.p1_syringe_DROPDOWN.currentText()
        self.p1_syringe_area = self.syringe_area_lookup.get(self.p1_syringe, 1.0)
        self.display_p1_syringe()

        self.set_p1_units()
        self.set_p1_speed()
        self.set_p1_accel()
        self.set_p1_setup_jog_delta()
        self.set_p1_amount()

    def set_p2_syringe(self):
        self.p2_syringe = self.ui.p2_syringe_DROPDOWN.currentText()
        self.p2_syringe_area = self.syringe_area_lookup.get(self.p2_syringe, 1.0)
        self.display_p2_syringe()

        self.set_p2_units()
        self.set_p2_speed()
        self.set_p2_accel()
        self.set_p2_setup_jog_delta()
        self.set_p2_amount()

    def set_p3_syringe(self):
        self.p3_syringe = self.ui.p3_syringe_DROPDOWN.currentText()
        self.p3_syringe_area = self.syringe_area_lookup.get(self.p3_syringe, 1.0)
        self.display_p3_syringe()

        self.set_p3_units()
        self.set_p3_speed()
        self.set_p3_accel()
        self.set_p3_setup_jog_delta()
        self.set_p3_amount()

    def set_p4_syringe(self):
        self.p4_syringe = self.ui.p4_syringe_DROPDOWN.currentText()
        self.p4_syringe_area = self.syringe_area_lookup.get(self.p4_syringe, 1.0)
        self.display_p4_syringe()

        self.set_p4_units()
        self.set_p4_speed()
        self.set_p4_accel()
        self.set_p4_setup_jog_delta()
        self.set_p4_amount()

    # Set Px units
    def set_p1_units(self):
        self.p1_units = self.ui.p1_units_DROPDOWN.currentText()

        length = self.p1_units.split("/")[0]
        self.ui.p1_units_LABEL_2.setText(length)

        self.set_p1_speed()
        self.set_p1_accel()
        self.set_p1_setup_jog_delta()
        self.set_p1_amount()

    def set_p2_units(self):
        self.p2_units = self.ui.p2_units_DROPDOWN.currentText()

        length = self.p2_units.split("/")[0]
        self.ui.p2_units_LABEL_2.setText(length)

        self.set_p2_speed()
        self.set_p2_accel()
        self.set_p2_setup_jog_delta()
        self.set_p2_amount()

    def set_p3_units(self):
        self.p3_units = self.ui.p3_units_DROPDOWN.currentText()

        length = self.p3_units.split("/")[0]
        self.ui.p3_units_LABEL_2.setText(length)

        self.set_p3_speed()
        self.set_p3_accel()
        self.set_p3_setup_jog_delta()
        self.set_p3_amount()

    def set_p4_units(self):
        self.p4_units = self.ui.p4_units_DROPDOWN.currentText()

        length = self.p4_units.split("/")[0]
        self.ui.p4_units_LABEL_2.setText(length)

        self.set_p4_speed()
        self.set_p4_accel()
        self.set_p4_setup_jog_delta()
        self.set_p4_amount()

    def populate_pump_units(self):
        self.units = ["mm/s", "mL/s", "mL/hr", "µL/hr"]
        self.ui.p1_units_DROPDOWN.addItems(self.units)
        self.ui.p2_units_DROPDOWN.addItems(self.units)
        self.ui.p3_units_DROPDOWN.addItems(self.units)
        self.ui.p4_units_DROPDOWN.addItems(self.units)

    def populate_pump_jog_delta(self):
        self.jog_delta = ["0.01", "0.1", "1.0", "10.0"]
        self.ui.p1_setup_jog_delta_INPUT.addItems(self.jog_delta)
        self.ui.p2_setup_jog_delta_INPUT.addItems(self.jog_delta)
        self.ui.p3_setup_jog_delta_INPUT.addItems(self.jog_delta)
        self.ui.p4_setup_jog_delta_INPUT.addItems(self.jog_delta)

    # Set Px speed
    def set_p1_speed(self):
        self.p1_speed = self.ui.p1_speed_INPUT.value()
        self.ui.p1_units_LABEL.setText(
            str(self.p1_speed) + " " + self.ui.p1_units_DROPDOWN.currentText()
        )
        self.p1_speed_to_send = self.convert_speed(
            self.p1_speed, self.p1_units, self.p1_syringe_area, self.microstepping
        )

    def set_p2_speed(self):
        self.p2_speed = self.ui.p2_speed_INPUT.value()
        self.ui.p2_units_LABEL.setText(
            str(self.p2_speed) + " " + self.ui.p2_units_DROPDOWN.currentText()
        )
        self.p2_speed_to_send = self.convert_speed(
            self.p2_speed, self.p2_units, self.p2_syringe_area, self.microstepping
        )

    def set_p3_speed(self):
        self.p3_speed = self.ui.p3_speed_INPUT.value()
        self.ui.p3_units_LABEL.setText(
            str(self.p3_speed) + " " + self.ui.p3_units_DROPDOWN.currentText()
        )
        self.p3_speed_to_send = self.convert_speed(
            self.p3_speed, self.p3_units, self.p3_syringe_area, self.microstepping
        )

    def set_p4_speed(self):
        self.p4_speed = self.ui.p4_speed_INPUT.value()
        self.ui.p4_units_LABEL.setText(
            str(self.p4_speed) + " " + self.ui.p4_units_DROPDOWN.currentText()
        )
        self.p4_speed_to_send = self.convert_speed(
            self.p4_speed, self.p4_units, self.p4_syringe_area, self.microstepping
        )

    # Set Px accel
    def set_p1_accel(self):
        self.p1_accel = self.ui.p1_accel_INPUT.value()
        self.p1_accel_to_send = self.convert_accel(
            self.p1_accel, self.p1_units, self.p1_syringe_area, self.microstepping
        )

    def set_p2_accel(self):
        self.p2_accel = self.ui.p2_accel_INPUT.value()
        self.p2_accel_to_send = self.convert_accel(
            self.p2_accel, self.p2_units, self.p2_syringe_area, self.microstepping
        )

    def set_p3_accel(self):
        self.p3_accel = self.ui.p3_accel_INPUT.value()
        self.p3_accel_to_send = self.convert_accel(
            self.p3_accel, self.p3_units, self.p3_syringe_area, self.microstepping
        )

    def set_p4_accel(self):
        self.p4_accel = self.ui.p4_accel_INPUT.value()
        self.p4_accel_to_send = self.convert_accel(
            self.p4_accel, self.p4_units, self.p4_syringe_area, self.microstepping
        )

    # Set Px jog delta (setup)
    def set_p1_setup_jog_delta(self):
        self.p1_setup_jog_delta = float(self.ui.p1_setup_jog_delta_INPUT.currentText())
        self.p1_setup_jog_delta_to_send = self.convert_displacement(
            self.p1_setup_jog_delta,
            self.p1_units,
            self.p1_syringe_area,
            self.microstepping,
        )

    def set_p2_setup_jog_delta(self):
        self.p2_setup_jog_delta = float(self.ui.p2_setup_jog_delta_INPUT.currentText())
        self.p2_setup_jog_delta_to_send = self.convert_displacement(
            self.p2_setup_jog_delta,
            self.p2_units,
            self.p2_syringe_area,
            self.microstepping,
        )

    def set_p3_setup_jog_delta(self):
        self.p3_setup_jog_delta = float(self.ui.p3_setup_jog_delta_INPUT.currentText())
        self.p3_setup_jog_delta_to_send = self.convert_displacement(
            self.p3_setup_jog_delta,
            self.p3_units,
            self.p3_syringe_area,
            self.microstepping,
        )

    def set_p4_setup_jog_delta(self):
        self.p4_setup_jog_delta = float(self.ui.p4_setup_jog_delta_INPUT.currentText())
        self.p4_setup_jog_delta_to_send = self.convert_displacement(
            self.p4_setup_jog_delta,
            self.p4_units,
            self.p4_syringe_area,
            self.microstepping,
        )

    def generate_pump_setting_commands(self, pump_id):
        speed = getattr(self, f"p{pump_id}_speed_to_send")
        accel = getattr(self, f"p{pump_id}_accel_to_send")
        delta = getattr(self, f"p{pump_id}_setup_jog_delta_to_send")
        return [
            f"<SETTING,SPEED,{pump_id},{speed},F,0.0,0.0,0.0>",
            f"<SETTING,ACCEL,{pump_id},{accel},F,0.0,0.0,0.0>",
            f"<SETTING,DELTA,{pump_id},{delta},F,0.0,0.0,0.0>",
        ]

    def send_settings_for_pump(self, pump_id):
        controller_id = self.pump_to_controller.get(pump_id)
        label = self.controller_labels.get(controller_id, "Controller")
        if not controller_id or not self.serial_ports.get(controller_id):
            self.statusBar().showMessage(f"{label} is not connected.")
            return

        commands = [
            (controller_id, cmd) for cmd in self.generate_pump_setting_commands(pump_id)
        ]
        self.dispatch_commands(commands)

    # Send Px settings
    def send_p1_settings(self):
        self.statusBar().showMessage("You clicked SEND P1 SETTINGS")
        self.send_settings_for_pump(1)

    def send_p2_settings(self):
        self.statusBar().showMessage("You clicked SEND P2 SETTINGS")
        self.send_settings_for_pump(2)

    def send_p3_settings(self):
        self.statusBar().showMessage("You clicked SEND P3 SETTINGS")
        self.send_settings_for_pump(3)

    def send_p4_settings(self):
        self.statusBar().showMessage("You clicked SEND P4 SETTINGS")
        self.send_settings_for_pump(4)

    def connect_controller(self, controller_id):
        port = self.selected_ports.get(controller_id, "")
        label = self.controller_labels.get(controller_id, controller_id.title())
        if not port:
            self.statusBar().showMessage(
                f"Select a port for {label} before connecting."
            )
            return

        if self.serial_ports.get(controller_id):
            self.statusBar().showMessage(f"{label} is already connected.")
            return

        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = 230400
            ser.parity = serial.PARITY_NONE
            ser.stopbits = serial.STOPBITS_ONE
            ser.bytesize = serial.EIGHTBITS
            ser.timeout = 1
            ser.open()
            self.serial_ports[controller_id] = ser
            time.sleep(1.0)
            self.statusBar().showMessage(f"Connected to {label} on {port}.")
            self.update_connection_ui(controller_id, True)
            self.update_component_states()
        except Exception as exc:
            self.statusBar().showMessage(f"Failed to connect to {label}: {exc}")
            traceback.print_exc()

    def disconnect_controller(self, controller_id):
        label = self.controller_labels.get(controller_id, controller_id.title())
        ser = self.serial_ports.get(controller_id)
        if ser is None:
            self.statusBar().showMessage(f"{label} is not connected.")
            return

        try:
            ser.close()
        except Exception as exc:
            self.statusBar().showMessage(f"Error while disconnecting {label}: {exc}")
        finally:
            self.serial_ports[controller_id] = None
            self.update_connection_ui(controller_id, False)
            self.update_component_states()

    def update_connection_ui(self, controller_id, connected):
        if controller_id == "primary":
            status_label = self.ui.primary_status_LABEL
            connect_btn = self.ui.primary_connect_BTN
            disconnect_btn = self.ui.primary_disconnect_BTN
        else:
            status_label = self.ui.secondary_status_LABEL
            connect_btn = self.ui.secondary_connect_BTN
            disconnect_btn = self.ui.secondary_disconnect_BTN

        if connected:
            port = self.selected_ports.get(controller_id, "")
            status_label.setText(f"Connected ({port})" if port else "Connected")
        else:
            status_label.setText("Disconnected")

        connect_btn.setEnabled(not connected)
        disconnect_btn.setEnabled(connected)

    def update_component_states(self):
        controllers_connected = {
            cid: self.serial_ports.get(cid) is not None for cid in self.serial_ports
        }
        any_connected = any(controllers_connected.values())

        control_buttons = [
            self.ui.run_BTN,
            self.ui.pause_BTN,
            self.ui.zero_BTN,
            self.ui.stop_BTN,
            self.ui.jog_plus_BTN,
            self.ui.jog_minus_BTN,
        ]

        for btn in control_buttons:
            btn.setEnabled(any_connected)

        if any_connected:
            self.ui.run_BTN.setStyleSheet("background-color: green; color: black")
            self.ui.pause_BTN.setStyleSheet("background-color: yellow; color: black")
            self.ui.stop_BTN.setStyleSheet("background-color: red; color: black")
        else:
            self.ui.run_BTN.setStyleSheet("")
            self.ui.pause_BTN.setStyleSheet("")
            self.ui.stop_BTN.setStyleSheet("")

        for pump_id in range(1, 5):
            controller_id = self.pump_to_controller.get(pump_id)
            connected = controllers_connected.get(controller_id, False)
            send_btn = getattr(self.ui, f"p{pump_id}_setup_send_BTN")
            checkbox = getattr(self.ui, f"p{pump_id}_activate_CHECKBOX")
            send_btn.setEnabled(connected)
            checkbox.setEnabled(connected)
            if not connected and checkbox.isChecked():
                checkbox.setChecked(False)

        self.ui.send_all_BTN.setEnabled(any_connected)

    def dispatch_commands(self, controller_commands):
        grouped_commands = defaultdict(list)
        for controller_id, command in controller_commands:
            ser = self.serial_ports.get(controller_id)
            if ser is None:
                label = self.controller_labels.get(controller_id, controller_id)
                self.statusBar().showMessage(f"{label} is not connected.")
                continue
            grouped_commands[controller_id].append(command)

        for controller_id, commands in grouped_commands.items():
            if not commands:
                continue
            thread = Thread(self.run_serial_sequence, controller_id, commands)
            thread.finished.connect(lambda th=thread: self.thread_finished(th))
            thread.start()

    # Send all settings
    def send_all(self):
        self.statusBar().showMessage("You clicked SEND ALL SETTINGS")

        controller_commands = []
        for pump_id in range(1, 5):
            controller_id = self.pump_to_controller.get(pump_id)
            if not controller_id or not self.serial_ports.get(controller_id):
                continue
            for cmd in self.generate_pump_setting_commands(pump_id):
                controller_commands.append((controller_id, cmd))

        if controller_commands:
            print("Sending all settings..")
            self.dispatch_commands(controller_commands)
            self.send_p1_success()
            self.send_p2_success()
            self.send_p3_success()
            self.send_p4_success()
            print("All settings sent.")
        else:
            self.statusBar().showMessage(
                "No controllers connected to receive settings."
            )

    # =======================
    # MISC : Functions I need
    # =======================

    def steps2mm(self, steps, microsteps):
        # 200 steps per rev
        # one rev is 8mm dist
        mm = steps / 200 / microsteps * 8.0
        return mm

    def steps2mL(self, steps, syringe_area):
        mL = self.mm32mL(self.steps2mm(steps) * syringe_area)
        return mL

    def steps2uL(self, steps, syringe_area):
        uL = self.mm32uL(self.steps2mm(steps) * syringe_area)
        return uL

    def mm2steps(self, mm, microsteps):
        steps = mm / 8.0 * 200 * microsteps
        return steps

    def mL2steps(self, mL, syringe_area, microsteps):
        # note syringe_area is in mm^2
        steps = self.mm2steps(self.mL2mm3(mL) / syringe_area, microsteps)
        return steps

    def uL2steps(self, uL, syringe_area, microsteps):
        steps = self.mm2steps(self.uL2mm3(uL) / syringe_area, microsteps)
        return steps

    def mL2uL(self, mL):
        return mL * 1000.0

    def mL2mm3(self, mL):
        return mL * 1000.0

    def uL2mL(self, uL):
        return uL / 1000.0

    def uL2mm3(self, uL):
        return uL

    def mm32mL(self, mm3):
        return mm3 / 1000.0

    def mm32uL(self, mm3):
        return mm3

    def persec2permin(self, value_per_sec):
        value_per_min = value_per_sec * 60.0
        return value_per_min

    def persec2perhour(self, value_per_sec):
        value_per_hour = value_per_sec * 60.0 * 60.0
        return value_per_hour

    def permin2perhour(self, value_per_min):
        value_per_hour = value_per_min * 60.0
        return value_per_hour

    def permin2persec(self, value_per_min):
        value_per_sec = value_per_min / 60.0
        return value_per_sec

    def perhour2permin(self, value_per_hour):
        value_per_min = value_per_hour / 60.0
        return value_per_min

    def perhour2persec(self, value_per_hour):
        value_per_sec = value_per_hour / 60.0 / 60.0
        return value_per_sec

    def convert_displacement(self, displacement, units, syringe_area, microsteps):
        length = units.split("/")[0]
        time = units.split("/")[1]
        inp_displacement = displacement
        # convert length first
        if length == "mm":
            displacement = self.mm2steps(displacement, microsteps)
        elif length == "mL":
            displacement = self.mL2steps(displacement, syringe_area, microsteps)
        elif length == "µL":
            displacement = self.uL2steps(displacement, syringe_area, microsteps)

        print("______________________________")
        print("INPUT  DISPLACEMENT: " + str(inp_displacement) + " " + length)
        print("OUTPUT DISPLACEMENT: " + str(displacement) + " steps")
        print("\n############################################################\n")
        return displacement

    def convert_speed(self, inp_speed, units, syringe_area, microsteps):
        length = units.split("/")[0]
        time = units.split("/")[1]

        # convert length first
        if length == "mm":
            speed = self.mm2steps(inp_speed, microsteps)
        elif length == "mL":
            speed = self.mL2steps(inp_speed, syringe_area, microsteps)
        elif length == "µL":
            speed = self.uL2steps(inp_speed, syringe_area, microsteps)

        # convert time next
        if time == "s":
            pass
        elif time == "min":
            speed = self.permin2persec(speed)
        elif time == "hr":
            speed = self.perhour2persec(speed)

        print("INPUT  SPEED: " + str(inp_speed) + " " + units)
        print("OUTPUT SPEED: " + str(speed) + " steps/s")
        return speed

    def convert_accel(self, accel, units, syringe_area, microsteps):
        length = units.split("/")[0]
        time = units.split("/")[1]
        inp_accel = accel
        accel = accel

        # convert length first
        if length == "mm":
            accel = self.mm2steps(accel, microsteps)
        elif length == "mL":
            accel = self.mL2steps(accel, syringe_area, microsteps)
        elif length == "µL":
            accel = self.uL2steps(accel, syringe_area, microsteps)

        # convert time next
        if time == "s":
            pass
        elif time == "min":
            accel = self.permin2persec(self.permin2persec(accel))
        elif time == "hr":
            accel = self.perhour2persec(self.perhour2persec(accel))

        print("______________________________")
        print("INPUT  ACCEL: " + str(inp_accel) + " " + units + "/" + time)
        print("OUTPUT ACCEL: " + str(accel) + " steps/s/s")
        return accel

    """
        Syringe Volume (mL)    |        Syringe Area (mm^2)
    -----------------------------------------------
        1                |            17.34206347
        3                |            57.88559215
        5                |            112.9089185
        10                |            163.539454
        20                |            285.022957
        30                |            366.0961536
        60                |            554.0462538

    IMPORTANT: These are for BD Plastic syringes ONLY!! Others will vary.
    """
    # ====================================== Reading and Writing to Arduino

    def send_to_serial(self, ser, command):
        ser.write(command.encode())
        ser.flushInput()

    def recv_position_from_serial(self, ser, controller_id):
        startMarker = self.startMarker
        midMarker = self.midMarker
        endMarker = self.endMarker

        ck = ""
        x = "z"  # any value that is not an end- or startMarker

        while ord(x) != startMarker:
            x = ser.read()

        while ord(x) != endMarker:
            if ord(x) == midMarker:
                print(ck)
                if controller_id == "primary":
                    self.ui.p1_absolute_DISP.display(ck)
                ck = ""
                x = ser.read()
                continue

            if ord(x) != startMarker:
                ck = ck + x.decode()

            x = ser.read()

        return ck

    def run_serial_sequence(self, controller_id, commands):
        ser = self.serial_ports.get(controller_id)
        if ser is None:
            print(f"Controller {controller_id} not connected; skipping commands.")
            return

        numLoops = len(commands)
        waitingForReply = False
        n = 0

        while n < numLoops:
            command = commands[n]

            if not waitingForReply:
                self.send_to_serial(ser, command)
                print(f"Sent from PC ({controller_id}) -- {command}")
                waitingForReply = True

            if waitingForReply:
                while ser.inWaiting() == 0:
                    QtWidgets.QApplication.processEvents()

                dataRecvd = self.recv_position_from_serial(ser, controller_id)
                print(f"Reply Received ({controller_id}) -- {dataRecvd}")
                n += 1
                waitingForReply = False

            time.sleep(0.1)
        print("Send and receive complete\n\n")

    def listening(self):
        startMarker = self.startMarker
        midMarker = self.midMarker
        endMarker = self.endMarker
        posMarker = ord("?")
        i = 0

        while True:
            self.serial.flushInput()
            x = "z"
            ck = ""
            isDisplay = "asdf"
            while self.serial.inWaiting() == 0:
                pass
            while ord(x) != startMarker:
                x = self.serial.read()
            # if ord(x) == posMarker:
            #     return self.get_position()
            while ord(x) != endMarker:
                if ord(x) == midMarker:
                    i += 1
                    print(ck)
                    # isDisplay = ck
                    # if i % 100 == 0:
                    #     self.ui.p1_absolute_DISP.display(ck)
                    ck = ""
                    x = self.serial.read()
                    continue
                if ord(x) != startMarker:
                    ck = ck + x.decode()
                x = self.serial.read()

                if ord(x) != startMarker:
                    ck = ck + x.decode()

                x = self.serial.read()
                # TODO
            # if isDisplay == "START":
            #    print("This is ck: " + ck)
            # motorID = int(ck)
            # self.is_p1_running = True
            # run thread(self.display_position, motorID)

            # toDisp = self.steps2mm(float(ck))
            # print("Pump num " + toDisp + " is now running.")i
            # self.ui.p1_absolute_DISP.display(toDisp)
            # isDisplay = ""

            # self.serial.flushInput()
            # print(self.serial.read(self.serial.inWaiting()).decode('ascii'))
            print(ck)
            print("\n")

    # TODO
    # def display_position(self, motorID):
    #     if motorID == 1:

    #         seconds = 0
    #         p1_speed = self.p1_speed_to_send
    #         p1_dist = 0
    #         p1_time = p1_dist/p1_speed

    #         time_start = time.start()
    #         while self.is_p1_running:
    #             pass

    def get_position(self):
        ck = ""
        x = self.serial.read()

        while ord(x) != self.endMarker:
            if ord(x) == self.midMarker:
                print(ck)
                ck = ""
                x = self.serial.read()
                continue
            ck = ck + x.decode()
            x = self.serial.read()
        print(ck)
        return ck

    def closeEvent(self, event):
        try:
            # self.global_listener_thread.stop()
            self.serial.close()
            # self.threadpool.end()

        except AttributeError:
            pass
        sys.exit()


# I feel better having one of these
def main():
    # a new app instance
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle("Poseidon Pumps Controller - Pachter Lab Caltech 2018")
    window.show()
    # without this, the script exits immediately.
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

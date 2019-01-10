import os
import sys
import ntpath
import numpy as np
import serial.tools.list_ports

from PyQt5.QtWidgets import (QComboBox, QMainWindow, QApplication, QWidget, QLabel, QLineEdit)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import pyqtSignal
from PyQt5 import QtCore

import matplotlib as mpl
mpl.use("QT5Agg")  # noqa: E402
from matplotlib.backends.qt_compat import QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvas
import matplotlib.pyplot as plt

import pyqtgraph as pg

from acconeer_utils.clients.reg.client import RegClient
from acconeer_utils.clients.json.client import JSONClient
from acconeer_utils.clients import configs

import data_processing

sys.path.append(os.path.join(os.path.dirname(__file__), "../examples/processing"))  # noqa: E402
import presence_detection as prd
import phase_tracking as pht
import breathing as br
import sleep_breathing as sb


class GUI(QMainWindow):
    sig_scan = pyqtSignal(object)
    use_cl = False
    data = None
    client = None
    sweep_count = -1
    acc_file = os.path.join(os.path.dirname(__file__), "acc.png")
    last_file = os.path.join(os.path.dirname(__file__), "last_config.npy")
    sweep_buffer = 500
    env_plot_max_y = 0

    def __init__(self):
        super().__init__()

        self.init_labels()
        self.init_textboxes()
        self.init_buttons()
        self.init_dropdowns()
        self.init_sublayouts()
        self.start_up()

        self.main_widget = QWidget()
        self.main_layout = QtWidgets.QGridLayout(self.main_widget)
        self.main_layout.sizeConstraint = QtWidgets.QLayout.SetDefaultConstraint

        self.main_layout.addLayout(self.panel_sublayout, 0, 1)
        self.main_layout.setColumnStretch(0, 1)

        self.canvas = self.init_graphs()
        self.main_layout.addWidget(self.canvas, 0, 0)

        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.setGeometry(50, 50, 1200, 700)
        self.setWindowTitle("Acconeer Exploration GUI")
        self.show()

        self.radar = data_processing.DataProcessing()

    def init_labels(self):
        text = {
            "sensor":       "Sensor",
            "server":       "Host address",
            "scan":         "Scan",
            "gain":         "Gain",
            "frequency":    "Sample frequency",
            "sweeps":       "Number of sweeps",
            "sweep_buffer": "Sweep buffer",
            "start_range":  "Start (m)",
            "end_range":    "Stop (m)",
            "clutter":      "Clutter settings",
            "clutter_file": "",
            "interface":    "Interface"
        }

        self.labels = {}
        for key in text:
            self.labels[key] = QLabel(self)
        for key, val in self.labels.items():
            val.setText(text[key])

    def init_textboxes(self):
        text = {
            "sensor":       "1",
            "host":         "192.168.1.100",
            "frequency":    "10",
            "sweeps":       "-1",
            "gain":         "0.4",
            "start_range":  "0.18",
            "end_range":    "0.72",
            "sweep_buffer": "100",
        }
        self.textboxes = {}
        for key in text:
            self.textboxes[key] = QLineEdit(self)
            self.textboxes[key].setText(text[key])

    def init_graphs(self, mode="Select service"):
        axes = {
            "Select service": [None, None],
            "IQ": [None, None],
            "Envelope": [None, None],
            "Presence detection": [prd, prd.PresenceDetectionProcessor],
            "Breathing": [br, br.BreathingProcessor],
            "Phase tracking": [pht, pht.PhaseTrackingProcessor],
            "Sleep breathing": [sb, sb.PresenceDetectionProcessor],
        }

        self.external = axes[mode][1]
        canvas = None

        if mode == "Select service":
            canvas = QLabel()
            pixmap = QPixmap(self.acc_file)
            canvas.setPixmap(pixmap)
            self.current_canvas = mode
            return canvas

        if self.external:
            self.fig = plt.figure(tight_layout=True)
            self.service_fig = axes[mode][0].ExampleFigureUpdater(self.update_sensor_config())
            self.external = axes[mode][1]
            self.service_fig.setup(self.fig)
            canvas = FigureCanvas(self.fig)
            canvas.figure.set_facecolor("#f0f0f0")
            canvas.draw()
        else:
            pg.setConfigOption("background", "#f0f0f0")
            pg.setConfigOption("leftButtonPan", False)
            pg.setConfigOptions(antialias=True)
            canvas = pg.GraphicsLayoutWidget()
            self.envelope_plot_window = canvas.addPlot(title="Envelope")
            self.envelope_plot_window.showGrid(x=True, y=True)
            self.envelope_plot_window.addLegend()
            font = QFont()
            font.setPixelSize(18)
            self.envelope_plot_window.getAxis("bottom").tickFont = font
            font.setPixelSize(12)
            self.envelope_plot_window.getAxis("left").tickFont = font
            pen = pg.mkPen("r", width=5)
            self.envelope_plot = self.envelope_plot_window.plot(range(10),
                                                                np.zeros(10),
                                                                pen=pen,
                                                                name="Envelope")
            self.envelope_plot_window.setYRange(0, 1)
            pen = pg.mkPen(width=5, style=QtCore.Qt.DotLine)
            self.clutter_plot = self.envelope_plot_window.plot(range(10),
                                                               np.zeros(10),
                                                               pen=pen,
                                                               name="Clutter")
            self.clutter_plot.setZValue(2)

            self.snr_text = pg.TextItem(text="", color=(1, 1, 1), anchor=(0, 1))
            self.snr_text.setZValue(3)
            self.envelope_plot_window.addItem(self.snr_text)
            canvas.nextRow()
            if mode.lower() == "iq":
                self.iq_plot_window = canvas.addPlot(title="Phase")
                self.iq_plot_window.showGrid(x=True, y=True)
                self.iq_plot_window.addLegend()
                font = QFont()
                font.setPixelSize(18)
                self.iq_plot_window.getAxis("bottom").tickFont = font
                font.setPixelSize(12)
                self.iq_plot_window.getAxis("left").tickFont = font
                pen = pg.mkPen("g", width=5)
                self.iq_plot = self.iq_plot_window.plot(range(10),
                                                        np.arange(10)*0,
                                                        pen=pen,
                                                        name="IQ Phase")
                canvas.nextRow()
            self.hist_plot_image = canvas.addPlot()
            self.hist_plot = pg.ImageItem(titel="History")
            colormap = plt.get_cmap("viridis")
            colormap._init()
            lut = (colormap._lut * 255).view(np.ndarray)
            self.hist_plot.setLookupTable(lut)
            pen = pg.mkPen("r", width=5)
            self.hist_plot_peak = self.hist_plot_image.plot(range(10),
                                                            np.zeros(10),
                                                            pen=pen)
            self.hist_plot_image.addItem(self.hist_plot)

        self.current_canvas = mode
        return canvas

    def init_dropdowns(self):
        self.mode = QComboBox(self)
        self.mode.addItem("Select service")
        self.mode.addItem("IQ")
        self.mode.addItem("Envelope")
        self.mode.addItem("Phase tracking")
        self.mode.addItem("Presence detection")
        self.mode.addItem("Breathing")
        self.mode.addItem("Sleep breathing")
        self.mode.move(50, 250)

        self.mode_to_param = {
            "Select service": "",
            "IQ": "iq_data",
            "Envelope": "envelope_data",
            "Breathing": "iq_data",
            "Phase tracking": "iq_data",
            "Presence detection": "iq_data",
            "Sleep breathing": "iq_data",
        }

        self.mode_to_config = {
            "Select service": ["", ""],
            "IQ": [configs.IQServiceConfig(), "internal"],
            "Envelope": [configs.EnvelopeServiceConfig(), "internal"],
            "Breathing": [br.get_base_config(), "external"],
            "Phase tracking": [pht.get_base_config(), "external"],
            "Presence detection": [prd.get_base_config(), "external"],
            "Sleep breathing": [sb.get_base_config(), "external"],
        }

        self.mode.currentIndexChanged.connect(self.update_canvas)

        self.interface = QComboBox(self)
        self.interface.addItem("Socket")
        self.interface.addItem("Serial")
        self.interface.currentIndexChanged.connect(self.update_interface)

        self.ports = QComboBox(self)
        self.ports.addItem("Scan ports")
        self.ports.activated.connect(self.update_ports)
        self.update_ports()

    def update_ports(self):
        if "scan" not in self.ports.currentText().lower():
            return

        port_infos = serial.tools.list_ports.comports()
        ports = [port_info[0] for port_info in port_infos]

        self.ports.clear()
        self.ports.addItem("Scan ports")
        self.ports.addItems(ports)

    def init_buttons(self):
        self.buttons = {
            "start":        QtWidgets.QPushButton("Start", self),
            "connect":      QtWidgets.QPushButton("Connect", self),
            "stop":         QtWidgets.QPushButton("Stop", self),
            "create_cl":    QtWidgets.QPushButton("Scan Clutter", self),
            "load_cl":      QtWidgets.QPushButton("Load Clutter", self),
            "load_scan":    QtWidgets.QPushButton("Load Scan", self),
            "save_scan":    QtWidgets.QPushButton("Save Scan", self),
        }

        button_funcs = {
            "start": self.start_scan,
            "connect": self.connect_to_server,
            "stop": self.stop_scan,
            "create_cl": lambda: self.start_scan(create_cl=True),
            "load_cl": self.load_clutter_file,
            "load_scan": self.load_scan,
            "save_scan": lambda: self.save_scan(self.data),
        }

        button_enabled = {
            "start": False,
            "connect": True,
            "stop": True,
            "create_cl": False,
            "load_cl": True,
            "load_scan": True,
            "save_scan": False,
        }

        for key in button_funcs:
            self.buttons[key].clicked.connect(button_funcs[key])
            self.buttons[key].setEnabled(button_enabled[key])

    def init_sublayouts(self):
        # Panel sublayout
        self.panel_sublayout = QtWidgets.QHBoxLayout()
        panel_sublayout_inner = QtWidgets.QVBoxLayout()

        # Server sublayout
        server_sublayout_grid = QtWidgets.QGridLayout()
        server_sublayout_grid.addWidget(self.labels["server"], 0, 0)
        server_sublayout_grid.addWidget(self.labels["interface"], 0, 1)
        server_sublayout_grid.addWidget(self.ports, 1, 0)
        server_sublayout_grid.addWidget(self.textboxes["host"], 1, 0)
        server_sublayout_grid.addWidget(self.interface, 1, 1)
        server_sublayout_grid.addWidget(self.mode, 2, 0)
        server_sublayout_grid.addWidget(self.buttons["connect"], 2, 1)

        # Controls sublayout
        control_sublayout_grid = QtWidgets.QGridLayout()
        control_sublayout_grid.addWidget(self.labels["scan"], 0, 0)
        control_sublayout_grid.addWidget(self.buttons["start"], 1, 0)
        control_sublayout_grid.addWidget(self.buttons["stop"], 1, 1)
        control_sublayout_grid.addWidget(self.buttons["save_scan"], 2, 0)
        control_sublayout_grid.addWidget(self.buttons["load_scan"], 2, 1)
        control_sublayout_grid.addWidget(self.labels["clutter"], 3, 0)
        control_sublayout_grid.addWidget(self.buttons["create_cl"], 4, 0)
        control_sublayout_grid.addWidget(self.buttons["load_cl"], 4, 1)
        control_sublayout_grid.addWidget(self.labels["clutter_file"], 5, 0, 1, 2)

        # Settings sublayout
        settings_sublayout_grid = QtWidgets.QGridLayout()
        settings_sublayout_grid.addWidget(self.labels["sensor"], 0, 0)
        settings_sublayout_grid.addWidget(self.textboxes["sensor"], 0, 1)
        settings_sublayout_grid.addWidget(self.labels["start_range"], 1, 0)
        settings_sublayout_grid.addWidget(self.labels["end_range"], 1, 1)
        settings_sublayout_grid.addWidget(self.textboxes["start_range"], 2, 0)
        settings_sublayout_grid.addWidget(self.textboxes["end_range"], 2, 1)
        settings_sublayout_grid.addWidget(self.labels["frequency"], 3, 0)
        settings_sublayout_grid.addWidget(self.textboxes["frequency"], 3, 1)
        settings_sublayout_grid.addWidget(self.labels["gain"], 4, 0)
        settings_sublayout_grid.addWidget(self.textboxes["gain"], 4, 1)
        settings_sublayout_grid.addWidget(self.labels["sweeps"], 5, 0)
        settings_sublayout_grid.addWidget(self.textboxes["sweeps"], 5, 1)
        settings_sublayout_grid.addWidget(self.labels["sweep_buffer"], 6, 0)
        settings_sublayout_grid.addWidget(self.textboxes["sweep_buffer"], 6, 1)

        panel_sublayout_inner.addStretch(10)
        panel_sublayout_inner.addLayout(server_sublayout_grid)
        panel_sublayout_inner.addStretch(2)
        panel_sublayout_inner.addLayout(control_sublayout_grid)
        panel_sublayout_inner.addStretch(4)
        panel_sublayout_inner.addLayout(settings_sublayout_grid)
        panel_sublayout_inner.addStretch(20)
        self.panel_sublayout.addStretch(5)
        self.panel_sublayout.addLayout(panel_sublayout_inner)
        self.panel_sublayout.addStretch(10)

    def update_canvas(self, force_update=False):
        mode = self.mode.currentText()

        if force_update or self.current_canvas not in mode:
            self.main_layout.removeWidget(self.canvas)
            self.canvas.deleteLater()
            self.canvas = None
            self.canvas = self.init_graphs(mode)
            self.main_layout.addWidget(self.canvas, 0, 0)

        self.update_sensor_config()

    def update_interface(self):
        if self.buttons["connect"].text() == "Disconnect":
            self.connect_to_server()

        if "serial" in self.interface.currentText().lower():
            self.ports.show()
            self.textboxes["host"].hide()
            self.labels["server"].setText("Serial port")
        else:
            self.ports.hide()
            self.textboxes["host"].show()
            self.labels["server"].setText("Host address")

    def error_message(self, error):
        em = QtWidgets.QErrorMessage(self.main_widget)
        em.setWindowTitle("Error")
        em.showMessage(error)

    def start_scan(self, create_cl=False, from_file=False):
        if "Select" in self.mode.currentText():
            self.error_message("Please select a service")
            return

        if self.external:
            self.update_canvas(force_update=True)

        data_source = "stream"
        if from_file:
            data_source = "file"
        sweep_buffer = 500
        try:
            sweep_buffer = int(self.textboxes["sweep_buffer"].text())
        except Exception:
            self.error_message("Sweep buffer needs to be a positive integer\n")
            self.textboxes["sweep_buffer"].setText("500")

        params = {
            "sensor_config": self.update_sensor_config(),
            "use_clutter": self.use_cl,
            "create_clutter": create_cl,
            "data_source": data_source,
            "data_type": self.mode_to_param[self.mode.currentText()],
            "service_type": self.mode.currentText(),
            "sweep_buffer": sweep_buffer,
        }

        self.threaded_scan = Threaded_Scan(params, parent=self)
        self.threaded_scan.sig_scan.connect(self.thread_receive)
        self.sig_scan.connect(self.threaded_scan.receive)

        self.buttons["start"].setEnabled(False)
        self.buttons["load_scan"].setEnabled(False)
        self.buttons["save_scan"].setEnabled(False)
        self.buttons["create_cl"].setEnabled(False)
        self.mode.setEnabled(False)
        self.interface.setEnabled(False)

        self.threaded_scan.start()

    def stop_scan(self):
        self.sig_scan.emit("stop")
        self.buttons["load_scan"].setEnabled(True)
        self.mode.setEnabled(True)
        self.interface.setEnabled(True)

    def connect_to_server(self):
        if self.buttons["connect"].text() == "Connect":
            max_num = 4
            if "Select service" in self.current_canvas:
                self.mode.setCurrentIndex(2)

            if self.interface.currentText().lower() == "socket":
                self.client = JSONClient(self.textboxes["host"].text())
            else:
                port = self.ports.currentText()
                if "scan" in port.lower():
                    self.error_message("Please select port first!")
                    return
                self.client = RegClient(port)
                max_num = 1

            conf = self.update_sensor_config()
            sensor = 1
            connection_success = False
            error = None
            while sensor <= max_num:
                conf.sensor = sensor
                try:
                    self.client.setup_session(conf)
                    self.client.start_streaming()
                    self.client.stop_streaming()
                    connection_success = True
                    self.textboxes["sensor"].setText("{:d}".format(sensor))
                    print(sensor)
                    break
                except Exception as e:
                    sensor += 1
                    error = e
            if connection_success:
                self.buttons["start"].setEnabled(True)
                self.buttons["create_cl"].setEnabled(True)
                self.buttons["stop"].setEnabled(True)
            else:
                self.error_message("Could not connect to sever!\n{}".format(error))
                return

            self.buttons["connect"].setText("Disconnect")
            self.buttons["connect"].setStyleSheet("QPushButton {color: red}")
        else:
            self.buttons["connect"].setText("Connect")
            self.buttons["connect"].setStyleSheet("QPushButton {color: black}")
            self.sig_scan.emit("stop")
            self.buttons["start"].setEnabled(False)
            self.buttons["create_cl"].setEnabled(False)

            try:
                self.client.stop_streaming()
            except Exception:
                pass

            try:
                self.client.disconnect()
            except Exception:
                pass

    def update_sensor_config(self):
        conf, service = self.mode_to_config[self.mode.currentText()]

        if not conf:
            return None

        external = service != "internal"

        conf.sensor = int(self.textboxes["sensor"].text())
        if external:
            color = "grey"
            self.textboxes["start_range"].setText(str(conf.range_interval[0]))
            self.textboxes["end_range"].setText(str(conf.range_interval[1]))
            self.textboxes["gain"].setText(str(conf.gain))
            self.textboxes["frequency"].setText(str(conf.sweep_rate))
            self.sweep_count = -1
        else:
            color = "white"
            conf.range_interval = [
                    float(self.textboxes["start_range"].text()),
                    float(self.textboxes["end_range"].text()),
            ]
            conf.sweep_rate = int(self.textboxes["frequency"].text())
            conf.gain = float(self.textboxes["gain"].text())
            self.sweep_count = int(self.textboxes["sweeps"].text())

        lock = {
            "start_range": True,
            "end_range": True,
            "frequency": True,
            "gain": True,
            "sweeps": True,
        }

        for key in lock:
            if "sensor" not in key and "host" not in key:
                self.textboxes[key].setReadOnly(external)
                style_sheet = "QLineEdit {{background-color: {}}}".format(color)
                self.textboxes[key].setStyleSheet(style_sheet)

        return conf

    def load_clutter_file(self):
        if "un" in self.buttons["load_cl"].text().lower():
            self.use_cl = None
            self.labels["clutter_file"].setText("")
            self.buttons["load_cl"].setText("Clutter")
            self.buttons["load_cl"].setStyleSheet("QPushButton {color: black}")
        else:
            options = QtWidgets.QFileDialog.Options()
            options |= QtWidgets.QFileDialog.DontUseNativeDialog
            fn, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self,
                    "QFileDialog.getOpenFileName()",
                    "",
                    "All Files (*);;NumPy data Files (*.npy)",
                    options=options
                    )

            if fn:
                self.use_cl = fn
                self.labels["clutter_file"].setText("Clutter: {}".format(ntpath.basename(fn)))
                self.buttons["load_cl"].setText("Unload clutter")
                self.buttons["load_cl"].setStyleSheet("QPushButton {color: red}")

    def load_scan(self):
        options = QtWidgets.QFileDialog.Options()
        options |= QtWidgets.QFileDialog.DontUseNativeDialog
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "QFileDialog.getOpenFileName()",
                "",
                "NumPy data files (*.npy)",
                options=options
                )

        if filename:
            try:
                self.data = np.load(filename)
                mode = self.data[0]["service_type"]
                index = self.mode.findText(mode, QtCore.Qt.MatchFixedString)
                if index >= 0:
                    self.mode.setCurrentIndex(index)
                    self.start_scan(from_file=True)
            except Exception as e:
                self.error_message("{}".format(e))

    def save_scan(self, data):
        if "sleep" in self.mode.currentText().lower():
            if int(self.textboxes["sweep_buffer"].text()) < 1000:
                self.error_message("Please set sweep buffer to >= 1000")
                return
        options = QtWidgets.QFileDialog.Options()
        options |= QtWidgets.QFileDialog.DontUseNativeDialog

        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "QFileDialog.getOpenFileName()",
                "",
                "NumPy data files (*.npy)",
                options=options
                )

        if filename:
            np.save(filename, data)

    def thread_receive(self, message_type, message, data=None):
        if "error" in message_type:
            self.error_message("{}".format(message))
            if "client" in message_type:
                if self.buttons["connect"].text() == "Disconnect":
                    self.connect_to_server()
                self.buttons["start"].setEnabled(False)
                self.buttons["create_cl"].setEnabled(False)
                self.mode.setEnabled(True)
                self.interface.setEnabled(True)
        elif message_type == "clutter_data":
            self.save_scan(data)
        elif message_type == "scan_data":
            self.data = data
            self.buttons["save_scan"].setEnabled(True)
        elif message_type == "scan_done":
            if "Disconnect" in self.buttons["connect"].text():
                self.buttons["start"].setEnabled(True)
                self.buttons["load_scan"].setEnabled(True)
                self.buttons["create_cl"].setEnabled(True)
                self.mode.setEnabled(True)
        elif "update_plots" in message_type:
            if data:
                self.update_plots(data)
        else:
            print(message_type, message, data)

    def update_plots(self, data):
        mode = self.mode.currentText()
        update_ylims = False
        xstart = data["x_mm"][0]
        xend = data["x_mm"][-1]
        xdim = data["hist_env"].shape[0]
        if not data["sweep"]:
            self.env_plot_max_y = 0
            update_ylims = True
            self.envelope_plot_window.setXRange(xstart, xend)
            self.snr_text.setPos(xstart, 0)

            if mode == "IQ":
                self.iq_plot_window.setXRange(xstart, xend)
                self.iq_plot_window.setYRange(-1.1, 1.1)

            xax = self.hist_plot_image.getAxis("left")
            x = np.round(np.arange(0, xdim+xdim/9, xdim/9))
            labels = np.round(np.arange(xstart, xend+(xend-xstart)/9,
                              (xend-xstart)/9))
            ticks = [list(zip(x, labels))]
            xax.setTicks(ticks)

        snr = "SNR@peak: N/A"
        if data["snr"] and np.isfinite(data["snr"]):
            snr = "SNR@peak: %.1fdB" % data["snr"]

        self.snr_text.setText(snr, color=(1, 1, 1))

        max_val = max(np.max(data["env_clutter"]+data["env_ampl"]), np.max(data["env_clutter"]))
        peak_line = np.flip((data["hist_plot"]-xstart)/(xend - xstart)*xdim, axis=0)

        self.envelope_plot.setData(data["x_mm"], data["env_ampl"] + data["env_clutter"])
        self.clutter_plot.setData(data["x_mm"], data["env_clutter"])

        ymax_level = min(1.5*np.max(np.max(data["hist_env"])), self.env_plot_max_y)

        self.hist_plot.updateImage(data["hist_env"].T, levels=(0, ymax_level))
        self.hist_plot_peak.setData(peak_line)
        self.hist_plot_peak.setZValue(2)

        if mode == "IQ":
            self.iq_plot.setData(data["x_mm"], data["phase"])

        if max_val > self.env_plot_max_y:
            self.env_plot_max_y = 1.2 * max_val
            update_ylims = True

        if update_ylims:
            self.envelope_plot_window.setYRange(0, self.env_plot_max_y)

        if self.sweep_buffer > data["sweep"]:
            self.hist_plot_image.setYRange(0, xdim)

    def start_up(self):
        if os.path.isfile(self.last_file):
            try:
                last = np.load(self.last_file)
            except Exception as e:
                print("Could not load settings from last session\n{}".format(e))
            self.update_settings(last.item()["sensor_config"], last.item())

    def update_settings(self, sensor_config, last_config=None):
        try:
            self.textboxes["gain"].setText("{:.1f}".format(sensor_config.gain))
            self.textboxes["frequency"].setText(str(sensor_config.sweep_rate))
            self.textboxes["start_range"].setText("{:.2f}".format(sensor_config.range_interval[0]))
            self.textboxes["end_range"].setText("{:.2f}".format(sensor_config.range_interval[1]))
            self.textboxes["sweep_buffer"].setText(last_config["sweep_buffer"])
            self.textboxes["sensor"].setText("{:d}".format(sensor_config.sensor[0]))
            self.interface.setCurrentIndex(last_config["interface"])
            self.ports.setCurrentIndex(last_config["port"])
        except Exception as e:
            print("Warning, could not restore last session\n{}".format(e))

        if last_config:
            self.textboxes["host"].setText(last_config["host"])
            self.sweep_count = last_config["sweep_count"]

    def closeEvent(self, event=None):
        if "select" not in str(self.mode.currentText()).lower():
            last_config = {
                "sensor_config": self.update_sensor_config(),
                "sweep_count": self.sweep_count,
                "host": self.textboxes["host"].text(),
                "sweep_buffer": self.textboxes["sweep_buffer"].text(),
                "interface": self.interface.currentIndex(),
                "port": self.ports.currentIndex(),
                }

            np.save(self.last_file, last_config)

        try:
            self.client.disconnect()
        except Exception:
            pass

        self.close()


class Threaded_Scan(QtCore.QThread):
    sig_scan = pyqtSignal(str, str, object)

    def __init__(self, params, parent=None):
        QtCore.QThread.__init__(self, parent)

        self.client = parent.client
        self.radar = parent.radar
        self.sensor_config = parent.update_sensor_config()
        self.params = params
        self.data = parent.data
        self.parent = parent
        self.running = True
        self.sweep_count = parent.sweep_count
        if self.sweep_count == -1:
            self.sweep_count = np.inf

    def run(self):
        if self.params["data_source"] == "stream":
            data = None

            try:
                self.client.setup_session(self.sensor_config)
                self.radar.prepare_processing(self, self.params)
                self.client.start_streaming()
            except Exception as e:
                self.emit("client_error", "Failed to communicate with server!\n"
                          "{}".format(self.format_error(e)))
                self.running = False

            try:
                while self.running:
                    info, sweep = self.client.get_next()
                    plot_data, data = self.radar.process(sweep)
                    if plot_data and plot_data["sweep"] + 1 >= self.sweep_count:
                        self.running = False
            except Exception as e:
                msg = "Failed to communicate with server!\n{}".format(self.format_error(e))
                self.emit("client_error", msg)

            try:
                self.client.stop_streaming()
            except Exception:
                pass

            if data:
                self.emit("scan_data", "", data)
        elif self.params["data_source"] == "file":
            self.radar.prepare_processing(self, self.params)
            self.radar.process_saved_data(self.data, self)
        else:
            self.emit("error", "Unknown mode %s!" % self.mode)
        self.emit("scan_done", "", "")

    def receive(self, message):
        if message == "stop":
            self.running = False
            self.radar.abort_processing()

    def emit(self, message_type, message, data=None):
        self.sig_scan.emit(message_type, message, data)

    def format_error(self, e):
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        err = "{}\n{}\n{}\n{}".format(exc_type, fname, exc_tb.tb_lineno, e)
        return err


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = GUI()
    sys.exit(app.exec_())

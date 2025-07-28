import sys
import os
import re
import sqlite3
import json
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QMessageBox, QFormLayout, QGroupBox, QAction, QListWidget, QStackedWidget
)
from PyQt5.QtGui import QPixmap, QFont, QIntValidator, QIcon, QPalette, QPainter
from PyQt5.QtCore import Qt, QRectF, QPoint

# --- Config Helper ---
class Config:
    def __init__(self, path="config.json"):
        self.path = path
        self.data = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def get_folder(self, key):
        return self.data.get(key, "")

    def set_folder(self, key, folder):
        self.data[key] = folder
        self.save()

# --- Database Helper ---
class UserDB:
    def __init__(self, db_path="users.db"):
        self.conn = sqlite3.connect(db_path)
        self.create_table()

    def create_table(self):
        self.conn.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )''')
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM users WHERE username='admin'")
        if not cur.fetchone():
            self.conn.execute("INSERT INTO users VALUES (?, ?, ?)", ('admin', 'admin', 'admin'))
            self.conn.commit()

    def validate(self, username, password):
        cur = self.conn.cursor()
        cur.execute("SELECT role FROM users WHERE username=? AND password=?", (username, password))
        row = cur.fetchone()
        return row[0] if row else None

# --- Enhanced Image Viewer with Zoom, Pan (no fit-to-display) ---
class EnhancedImageViewer(QGraphicsView):
    def __init__(self, image_path=None):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.pixmap = QPixmap(image_path) if image_path else QPixmap()
        self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
        self.scene().addItem(self.pixmap_item)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)
        self._zoom = 1.0
        self._panning = False
        self._start = None
        self._rect_item = None
        self._pan = False
        self._pan_start = QPoint()

    def load_image(self, path):
        self.scene().clear()
        self.pixmap = QPixmap(path)
        self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
        self.scene().addItem(self.pixmap_item)
        self.setSceneRect(QRectF(self.pixmap.rect()))
        self.resetTransform()
        self._zoom = 1.0

    def wheelEvent(self, event):
        zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(zoom_factor, zoom_factor)
        self._zoom *= zoom_factor

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pan = True
            self.setCursor(Qt.ClosedHandCursor)
            self._pan_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan and event.buttons() & Qt.LeftButton:
            delta = self._pan_start - event.pos()
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() + delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() + delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pan = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def zoom_in(self):
        self._zoom *= 1.25
        self.scale(1.25, 1.25)

    def zoom_out(self):
        self._zoom *= 0.8
        self.scale(0.8, 0.8)

    def reset_view(self):
        self.resetTransform()
        self._zoom = 1.0

# --- Image Viewer Window with Crop and Clipboard ---
class ImageViewerWindow(QMainWindow):
    def __init__(self, image_path):
        super().__init__()
        self.setWindowTitle("Image Viewer")
        self.viewer = EnhancedImageViewer(image_path)
        self._cropping = False
        self._start = None
        self._rect_item = None

        btn_zoom_in = QPushButton("Zoom In")
        btn_zoom_out = QPushButton("Zoom Out")
        btn_crop = QPushButton("Crop")
        btn_copy = QPushButton("Copy Crop")
        btn_reset = QPushButton("Reset")

        btn_zoom_in.clicked.connect(self.viewer.zoom_in)
        btn_zoom_out.clicked.connect(self.viewer.zoom_out)
        btn_reset.clicked.connect(self.viewer.reset_view)
        btn_crop.clicked.connect(self.activate_crop)
        btn_copy.clicked.connect(self.copy_crop)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(btn_zoom_in)
        btn_layout.addWidget(btn_zoom_out)
        btn_layout.addWidget(btn_crop)
        btn_layout.addWidget(btn_copy)
        btn_layout.addWidget(btn_reset)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.viewer)
        main_layout.addLayout(btn_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.viewer.viewport().installEventFilter(self)
        self._crop_mode = False

    def activate_crop(self):
        self._crop_mode = True
        self.viewer.setCursor(Qt.CrossCursor)

    def eventFilter(self, obj, event):
        if obj is self.viewer.viewport() and self._crop_mode:
            if event.type() == event.MouseButtonPress and event.button() == Qt.LeftButton:
                self._start = self.viewer.mapToScene(event.pos())
                if self._rect_item:
                    self.viewer.scene().removeItem(self._rect_item)
                    self._rect_item = None
                return True
            elif event.type() == event.MouseMove and self._start:
                end = self.viewer.mapToScene(event.pos())
                rect = QRectF(self._start, end).normalized()
                if self._rect_item:
                    self.viewer.scene().removeItem(self._rect_item)
                self._rect_item = self.viewer.scene().addRect(rect, pen=Qt.red)
                return True
            elif event.type() == event.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._crop_mode = False
                self.viewer.setCursor(Qt.ArrowCursor)
                return True
        return super().eventFilter(obj, event)

    def copy_crop(self):
        if self._rect_item:
            rect = self._rect_item.rect().toRect()
            cropped = self.viewer.pixmap.copy(rect)
            QApplication.clipboard().setPixmap(cropped)
            QMessageBox.information(self, "Copied", "Cropped image copied to clipboard.")

# --- Login Widget ---
class LoginWidget(QWidget):
    def __init__(self, db, on_login):
        super().__init__()
        self.db = db
        self.on_login = on_login
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        group = QGroupBox("Login")
        form = QFormLayout(group)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        btn = QPushButton("Login")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.try_login)
        form.addRow(btn)
        group.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(group)
        self.setLayout(layout)

    def try_login(self):
        username = self.user_edit.text()
        password = self.pass_edit.text()
        role = self.db.validate(username, password)
        if role:
            self.on_login(username, role)
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid username or password.")

# --- Fieldbook/Plot Register Viewer with Search and List Below ---
class BookViewer(QWidget):
    def __init__(self, config, config_key, title):
        super().__init__()
        self.config = config
        self.config_key = config_key
        self.title = title
        self.folder = self.config.get_folder(self.config_key)
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        # Left: Search Form (top) + List of Images (bottom)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        group = QGroupBox(self.title)
        form = QFormLayout(group)
        self.vdc_combo = QComboBox()
        self.ward_combo = QComboBox()
        self.sheet_combo = QComboBox()
        self.parcel_edit = QLineEdit()
        self.parcel_edit.setValidator(QIntValidator(1, 99999))
        self.search_btn = QPushButton("Search")
        self.search_btn.setMinimumHeight(36)
        self.search_btn.clicked.connect(self.search_image)
        form.addRow("VDC:", self.vdc_combo)
        form.addRow("Ward:", self.ward_combo)
        form.addRow("Sheet:", self.sheet_combo)
        form.addRow("Parcel No:", self.parcel_edit)
        form.addRow(self.search_btn)
        group.setContentsMargins(10, 10, 10, 10)
        left_layout.addWidget(group)
        self.image_list = QListWidget()
        left_layout.addWidget(QLabel("Available Images:"))
        left_layout.addWidget(self.image_list)
        left_layout.addStretch()
        left_widget.setMinimumWidth(350)
        left_widget.setMaximumWidth(500)

        # Right: Image Viewer
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.viewer = EnhancedImageViewer()
        # Add zoom in/out and reset buttons for preview pane
        btn_zoom_in = QPushButton("Zoom In")
        btn_zoom_out = QPushButton("Zoom Out")
        btn_reset = QPushButton("Reset")
        btn_zoom_in.clicked.connect(self.viewer.zoom_in)
        btn_zoom_out.clicked.connect(self.viewer.zoom_out)
        btn_reset.clicked.connect(self.viewer.reset_view)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(btn_zoom_in)
        btn_layout.addWidget(btn_zoom_out)
        btn_layout.addWidget(btn_reset)
        right_layout.addWidget(QLabel("Preview:"))
        right_layout.addWidget(self.viewer)
        right_layout.addLayout(btn_layout)
        right_widget.setMinimumWidth(400)

        main_layout.addWidget(left_widget, 35)
        main_layout.addWidget(right_widget, 65)
        self.setLayout(main_layout)

        self.vdc_combo.currentTextChanged.connect(self.update_wards)
        self.ward_combo.currentTextChanged.connect(self.update_sheets)
        self.sheet_combo.currentTextChanged.connect(self.update_images)
        self.image_list.currentTextChanged.connect(self.load_selected_image)
        self.populate_vdcs()

    def set_folder(self, folder):
        self.folder = folder
        self.populate_vdcs()

    def populate_vdcs(self):
        self.vdc_combo.clear()
        if not self.folder or not os.path.isdir(self.folder):
            return
        vdcs = [d for d in os.listdir(self.folder) if os.path.isdir(os.path.join(self.folder, d))]
        self.vdc_combo.addItems(vdcs)
        if vdcs:
            self.vdc_combo.setCurrentIndex(0)
            self.update_wards(vdcs[0])

    def update_wards(self, vdc):
        self.ward_combo.clear()
        vdc_path = os.path.join(self.folder, vdc)
        if not os.path.isdir(vdc_path):
            return
        # Sheet folders
        wards = [d for d in os.listdir(vdc_path) if os.path.isdir(os.path.join(vdc_path, d))]
        self.ward_combo.addItems(wards)
        # Add pseudo-ward for images directly inside VDC
        direct_images = [f for f in os.listdir(vdc_path) if re.match(r"(\d+)-(\d+)\.jpe?g", f, re.IGNORECASE)]
        if direct_images:
            self.ward_combo.addItem("(No Sheet)")
        if self.ward_combo.count() > 0:
            self.ward_combo.setCurrentIndex(0)
            self.update_sheets(self.ward_combo.currentText())


    def update_sheets(self, ward):
        vdc = self.vdc_combo.currentText()
        vdc_path = os.path.join(self.folder, vdc)
        self.sheet_combo.clear()
        if ward == "(No Sheet)":
            # No sheets for images directly in VDC
            self.update_images("(No Sheet)")
            return
        ward_path = os.path.join(vdc_path, ward)
        if not os.path.isdir(ward_path):
            return
        sheets = [d for d in os.listdir(ward_path) if os.path.isdir(os.path.join(ward_path, d))]
        self.sheet_combo.addItems(sheets)
        if sheets:
            self.sheet_combo.setCurrentIndex(0)
            self.update_images(sheets[0])


    def update_images(self, sheet):
        vdc = self.vdc_combo.currentText()
        ward = self.ward_combo.currentText()
        self.image_list.clear()
        # Images directly under VDC
        if ward == "(No Sheet)" or sheet == "(No Sheet)":
            vdc_path = os.path.join(self.folder, vdc)
            images = [f for f in os.listdir(vdc_path) if re.match(r"(\d+)-(\d+)\.jpe?g", f, re.IGNORECASE)]
            self.image_list.addItems(images)
            if images:
                self.image_list.setCurrentRow(0)
            return
        # Regular path: VDC/Ward/Sheet
        sheet_path = os.path.join(self.folder, vdc, ward, sheet)
        if not os.path.isdir(sheet_path):
            return
        images = [f for f in os.listdir(sheet_path) if re.match(r"(\d+)-(\d+)\.jpe?g", f, re.IGNORECASE)]
        self.image_list.addItems(images)
        if images:
            self.image_list.setCurrentRow(0)


    def load_selected_image(self, filename):
        vdc = self.vdc_combo.currentText()
        ward = self.ward_combo.currentText()
        sheet = self.sheet_combo.currentText()
        if ward == "(No Sheet)" or sheet == "(No Sheet)":
            path = os.path.join(self.folder, vdc, filename)
        else:
            path = os.path.join(self.folder, vdc, ward, sheet, filename)
        if os.path.isfile(path):
            self.viewer.load_image(path)


    def search_image(self):
        vdc = self.vdc_combo.currentText()
        ward = self.ward_combo.currentText()
        sheet = self.sheet_combo.currentText()
        parcel = self.parcel_edit.text()
        if not (vdc and parcel):
            QMessageBox.warning(self, "Error", "Please select all fields and enter a parcel number.")
            return
        found = False
        # Try images directly under VDC
        if ward == "(No Sheet)" or not ward:
            vdc_path = os.path.join(self.folder, vdc)
            for img in os.listdir(vdc_path):
                m = re.match(r"(\d+)-(\d+)\.jpe?g", img, re.IGNORECASE)
                if m and int(m.group(1)) <= int(parcel) <= int(m.group(2)):
                    image_path = os.path.join(vdc_path, img)
                    found = True
                    viewer = ImageViewerWindow(image_path)
                    viewer.show()
                    viewer.raise_()
                    viewer.activateWindow()
                    self._last_viewer = viewer
                    break
        else:
            # Try inside selection path
            sheet_path = os.path.join(self.folder, vdc, ward, sheet)
            for img in os.listdir(sheet_path):
                m = re.match(r"(\d+)-(\d+)\.jpe?g", img, re.IGNORECASE)
                if m and int(m.group(1)) <= int(parcel) <= int(m.group(2)):
                    image_path = os.path.join(sheet_path, img)
                    found = True
                    viewer = ImageViewerWindow(image_path)
                    viewer.show()
                    viewer.raise_()
                    viewer.activateWindow()
                    self._last_viewer = viewer
                    break
        if not found:
            QMessageBox.warning(self, "Not Found", "Parcel not found in this location.")


# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config
        self.setWindowTitle("Survey Office Image Manager")
        self.resize(1200, 800)
        self.font_family = "Mangal"
        self.username = None
        self.role = None
        self.stacked = QStackedWidget()
        self.setCentralWidget(self.stacked)
        self.init_menu()
        self.show_login()

    def init_menu(self):
        menubar = self.menuBar()
        self.menu_file = menubar.addMenu("File")
        self.action_set_fieldbook = QAction("Set Fieldbook Folder", self)
        self.action_set_fieldbook.triggered.connect(self.set_fieldbook_folder)
        self.menu_file.addAction(self.action_set_fieldbook)
        self.action_set_plotregister = QAction("Set Plot Register Folder", self)
        self.action_set_plotregister.triggered.connect(self.set_plotregister_folder)
        self.menu_file.addAction(self.action_set_plotregister)
        self.menu_file.addSeparator()
        self.action_logout = QAction("Logout", self)
        self.action_logout.triggered.connect(self.logout)
        self.menu_file.addAction(self.action_logout)
        self.menu_file.setEnabled(False)

    def show_login(self):
        self.menu_file.setEnabled(False)
        while self.stacked.count() > 0:
            widget = self.stacked.widget(0)
            self.stacked.removeWidget(widget)
            widget.deleteLater()
        self.login_widget = LoginWidget(self.db, self.on_login)
        self.stacked.addWidget(self.login_widget)
        self.stacked.setCurrentWidget(self.login_widget)

    def on_login(self, username, role):
        self.username = username
        self.role = role
        self.menu_file.setEnabled(True)
        self.show_home()

    def show_home(self):
        home = QWidget()
        layout = QVBoxLayout(home)
        label = QLabel(f"Welcome, {self.username}!")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 22px; font-weight: bold; margin: 20px;")
        layout.addWidget(label)
        card_layout = QHBoxLayout()
        btn_fieldbook = QPushButton(QIcon.fromTheme("folder"), "Fieldbook Viewer")
        btn_fieldbook.setMinimumSize(220, 120)
        btn_fieldbook.setStyleSheet("font-size: 20px; border-radius: 16px;")
        btn_fieldbook.clicked.connect(self.show_fieldbook)
        btn_plotregister = QPushButton(QIcon.fromTheme("folder"), "Plot Register Viewer")
        btn_plotregister.setMinimumSize(220, 120)
        btn_plotregister.setStyleSheet("font-size: 20px; border-radius: 16px;")
        btn_plotregister.clicked.connect(self.show_plotregister)
        card_layout.addWidget(btn_fieldbook)
        card_layout.addWidget(btn_plotregister)
        layout.addLayout(card_layout)
        layout.addStretch()
        self.stacked.addWidget(home)
        self.stacked.setCurrentWidget(home)

    def show_fieldbook(self):
        folder = self.config.get_folder("fieldbook_folder")
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "Set Folder", "Please set the Fieldbook folder from the File menu.")
            return
        self.fieldbook_viewer = BookViewer(self.config, "fieldbook_folder", "Fieldbook Viewer")
        self.stacked.addWidget(self.fieldbook_viewer)
        self.stacked.setCurrentWidget(self.fieldbook_viewer)

    def show_plotregister(self):
        folder = self.config.get_folder("plotregister_folder")
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "Set Folder", "Please set the Plot Register folder from the File menu.")
            return
        self.plotregister_viewer = BookViewer(self.config, "plotregister_folder", "Plot Register Viewer")
        self.stacked.addWidget(self.plotregister_viewer)
        self.stacked.setCurrentWidget(self.plotregister_viewer)

    def set_fieldbook_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Fieldbook Root Directory", os.getcwd())
        if folder:
            self.config.set_folder("fieldbook_folder", folder)
            QMessageBox.information(self, "Folder Set", "Fieldbook folder set successfully.")

    def set_plotregister_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Plot Register Root Directory", os.getcwd())
        if folder:
            self.config.set_folder("plotregister_folder", folder)
            QMessageBox.information(self, "Folder Set", "Plot Register folder set successfully.")

    def logout(self):
        self.username = None
        self.role = None
        while self.stacked.count() > 0:
            widget = self.stacked.widget(0)
            self.stacked.removeWidget(widget)
            widget.deleteLater()
        self.show_login()

# --- Main Entry Point ---
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(QPalette.Window, Qt.white)
    palette.setColor(QPalette.WindowText, Qt.black)
    palette.setColor(QPalette.Base, Qt.white)
    palette.setColor(QPalette.AlternateBase, Qt.lightGray)
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.black)
    palette.setColor(QPalette.Text, Qt.black)
    palette.setColor(QPalette.Button, Qt.white)
    palette.setColor(QPalette.ButtonText, Qt.black)
    palette.setColor(QPalette.Highlight, Qt.blue)
    palette.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget {
            font-family: 'Segoe UI', 'Mangal', 'Arial', sans-serif;
            font-size: 15px;
        }
        QMainWindow {
            background: #f7f7fa;
        }
        QGroupBox, QFrame {
            border: 1px solid #d0d0d0;
            border-radius: 12px;
            background: #ffffff;
            margin-top: 10px;
            padding: 12px;
        }
        QLabel {
            font-weight: 500;
        }
        QLineEdit, QComboBox, QTextEdit {
            border: 1.5px solid #b0b0b0;
            border-radius: 8px;
            padding: 6px 10px;
            background: #f9f9fc;
        }
        QComboBox QAbstractItemView {
            selection-background-color: #1976d2;
            selection-color: #ffffff;
            background: #f9f9fc;
            color: #222;
            border-radius: 0 0 8px 8px;
            outline: none;
        }
        QComboBox QAbstractItemView::item:hover {
            background: #1565c0;
            color: #fff;
        }
        QComboBox QAbstractItemView::item:selected {
            background: #1976d2;
            color: #fff;
        }
        QPushButton {
            background-color: #1976d2;
            color: white;
            border-radius: 8px;
            padding: 10px 20px;
            font-size: 16px;
            font-weight: 600;
            margin: 6px 0;
        }
        QPushButton:hover {
            background-color: #1565c0;
        }
        QListWidget, QGraphicsView {
            border: 1.5px solid #b0b0b0;
            border-radius: 8px;
            background: #f9f9fc;
        }
        QHeaderView::section {
            background-color: #e3eafc;
            border: none;
            padding: 6px;
        }
    """)
    db = UserDB()
    config = Config()
    window = MainWindow(db, config)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

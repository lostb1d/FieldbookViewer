import sys
import os
import re
import sqlite3
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QWidget, QComboBox, QFileDialog, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QInputDialog, QFormLayout, QTextEdit, QListWidget
)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QFont, QIntValidator
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

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

    def get_folder(self):
        return self.data.get("root_folder", "")

    def set_folder(self, folder):
        self.data["root_folder"] = folder
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

    def get_users(self):
        cur = self.conn.cursor()
        cur.execute("SELECT username, role FROM users")
        return cur.fetchall()

    def add_user(self, username, password, role):
        self.conn.execute("INSERT INTO users VALUES (?, ?, ?)", (username, password, role))
        self.conn.commit()

    def remove_user(self, username):
        self.conn.execute("DELETE FROM users WHERE username=?", (username,))
        self.conn.commit()

# --- Login Dialog ---
class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Login")
        self.setModal(True)
        layout = QVBoxLayout()
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("Username:"))
        layout.addWidget(self.user_edit)
        layout.addWidget(QLabel("Password:"))
        layout.addWidget(self.pass_edit)
        self.login_btn = QPushButton("Login")
        self.login_btn.setMinimumHeight(40)
        self.login_btn.clicked.connect(self.try_login)
        layout.addWidget(self.login_btn)
        self.setLayout(layout)
        self.role = None
        self.username = None

    def try_login(self):
        username = self.user_edit.text()
        password = self.pass_edit.text()
        role = self.db.validate(username, password)
        if role:
            self.role = role
            self.username = username
            self.accept()
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid username or password.")

# --- Admin User Management Dialog ---
class AdminDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("User Management")
        layout = QVBoxLayout()
        self.user_list = QListWidget()
        self.refresh_users()
        layout.addWidget(self.user_list)
        add_btn = QPushButton("Add User")
        add_btn.setMinimumHeight(40)
        add_btn.clicked.connect(self.add_user)
        del_btn = QPushButton("Delete User")
        del_btn.setMinimumHeight(40)
        del_btn.clicked.connect(self.del_user)
        layout.addWidget(add_btn)
        layout.addWidget(del_btn)
        self.setLayout(layout)

    def refresh_users(self):
        self.user_list.clear()
        for username, role in self.db.get_users():
            self.user_list.addItem(f"{username} ({role})")

    def add_user(self):
        username, ok = QInputDialog.getText(self, "Add User", "Username:")
        if not ok or not username:
            return
        password, ok = QInputDialog.getText(self, "Add User", "Password:")
        if not ok or not password:
            return
        role, ok = QInputDialog.getItem(self, "Add User", "Role:", ["admin", "surveyor"], 0, False)
        if not ok:
            return
        try:
            self.db.add_user(username, password, role)
            self.refresh_users()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Error", "User already exists.")

    def del_user(self):
        item = self.user_list.currentItem()
        if not item:
            return
        username = item.text().split()[0]
        if username == "admin":
            QMessageBox.warning(self, "Error", "Cannot delete admin user.")
            return
        self.db.remove_user(username)
        self.refresh_users()

# --- Image Viewer with Cropping ---
class ImageViewer(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.pixmap_item = None
        self._zoom = 1
        self._start = None
        self._rect_item = None
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def load_image(self, path):
        self.scene().clear()
        self.pixmap = QPixmap(path)
        self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
        self.scene().addItem(self.pixmap_item)
        self.setSceneRect(QRectF(self.pixmap.rect()))
        self._zoom = 1

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self._zoom *= factor
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = self.mapToScene(event.pos())
            if self._rect_item:
                self.scene().removeItem(self._rect_item)
                self._rect_item = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start:
            end = self.mapToScene(event.pos())
            rect = QRectF(self._start, end).normalized()
            if self._rect_item:
                self.scene().removeItem(self._rect_item)
            self._rect_item = self.scene().addRect(rect, pen=Qt.red)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._end = self.mapToScene(event.pos())
        super().mouseReleaseEvent(event)

    def get_crop_rect(self):
        if self._rect_item:
            return self._rect_item.rect().toRect()
        return None

    def crop_to_clipboard(self):
        rect = self.get_crop_rect()
        if rect and self.pixmap_item:
            cropped = self.pixmap.copy(rect)
            QApplication.clipboard().setPixmap(cropped)
            QMessageBox.information(self, "Copied", "Cropped image copied to clipboard.")
            return cropped
        return None

# --- Step-by-Step Main Window ---
class MainWindow(QMainWindow):
    def __init__(self, db, username, role, config):
        super().__init__()
        self.db = db
        self.username = username
        self.role = role
        self.config = config
        self.setWindowTitle("Survey Office Image Manager")
        self.resize(1200, 800)
        self.font_family = "Mangal"
        self.root_dir = self.config.get_folder()
        if not self.root_dir or not os.path.isdir(self.root_dir):
            self.select_folder()
        self.cropped_images = []
        self.user_details = {}
        self.header_text = ""
        self.footer_text = ""
        self.init_ui()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Root Directory", os.getcwd())
        if folder:
            self.root_dir = folder
            self.config.set_folder(folder)

    def init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(5)
        self.step = 0
        self.show_step()

    def show_step(self):
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        if self.step == 0:
            self.show_select_image_step()
        elif self.step == 1:
            self.show_crop_step()
        elif self.step == 2:
            self.show_finalize_step()
        elif self.step == 3:
            self.show_header_footer_step()
        elif self.step == 4:
            self.show_print_step()

    # Step 1: Select VDC, Ward, Sheet, Parcel (integer input)
    def show_select_image_step(self):
        group = QWidget()
        layout = QFormLayout(group)
        self.vdc_combo = QComboBox()
        self.ward_combo = QComboBox()
        self.sheet_combo = QComboBox()
        self.parcel_edit = QLineEdit()
        self.parcel_edit.setValidator(QIntValidator(1, 99999))
        layout.addRow("VDC:", self.vdc_combo)
        layout.addRow("Ward:", self.ward_combo)
        layout.addRow("Sheet:", self.sheet_combo)
        layout.addRow("Parcel No:", self.parcel_edit)
        self.populate_vdcs()
        self.vdc_combo.currentTextChanged.connect(self.update_wards)
        self.ward_combo.currentTextChanged.connect(self.update_sheets)
        self.sheet_combo.currentTextChanged.connect(self.update_parcels)
        btn = QPushButton("Show Image")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.select_image_next)
        layout.addRow(btn)
        group.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(group)

    def populate_vdcs(self):
        self.vdc_combo.clear()
        if not self.root_dir:
            return
        vdcs = [d for d in os.listdir(self.root_dir) if os.path.isdir(os.path.join(self.root_dir, d))]
        self.vdc_combo.addItems(vdcs)
        if vdcs:
            self.vdc_combo.setCurrentIndex(0)
            self.update_wards(vdcs[0])

    def update_wards(self, vdc):
        self.ward_combo.clear()
        vdc_path = os.path.join(self.root_dir, vdc)
        if not os.path.isdir(vdc_path):
            return
        wards = [d for d in os.listdir(vdc_path) if os.path.isdir(os.path.join(vdc_path, d))]
        self.ward_combo.addItems(wards)
        if wards:
            self.ward_combo.setCurrentIndex(0)
            self.update_sheets(wards[0])

    def update_sheets(self, ward):
        vdc = self.vdc_combo.currentText()
        sheet_path = os.path.join(self.root_dir, vdc, ward)
        self.sheet_combo.clear()
        if not os.path.isdir(sheet_path):
            return
        sheets = [d for d in os.listdir(sheet_path) if os.path.isdir(os.path.join(sheet_path, d))]
        self.sheet_combo.addItems(sheets)
        if sheets:
            self.sheet_combo.setCurrentIndex(0)
            self.update_parcels(sheets[0])

    def update_parcels(self, sheet):
        pass  # No action needed, as parcel is now integer input

    def select_image_next(self):
        vdc = self.vdc_combo.currentText()
        ward = self.ward_combo.currentText()
        sheet = self.sheet_combo.currentText()
        parcel = self.parcel_edit.text()
        if not (vdc and ward and sheet and parcel):
            QMessageBox.warning(self, "Error", "Please select all fields and enter a parcel number.")
            return
        # Find the image file for this parcel
        sheet_path = os.path.join(self.root_dir, vdc, ward, sheet)
        found = False
        for img in os.listdir(sheet_path):
            m = re.match(r"(\d+)-(\d+)\.jpe?g", img, re.IGNORECASE)
            if m:
                low, high = int(m.group(1)), int(m.group(2))
                if low <= int(parcel) <= high:
                    self.current_image_path = os.path.join(sheet_path, img)
                    self.current_selection = {
                        "vdc": vdc,
                        "ward": ward,
                        "sheet": sheet,
                        "parcel": parcel,
                        "img_file": img
                    }
                    found = True
                    break
        if not found:
            QMessageBox.warning(self, "Not Found", "Parcel not found in this sheet.")
            return
        self.step = 1
        self.show_step()

    # Step 2: Crop and Copy
    def show_crop_step(self):
        self.viewer = ImageViewer()
        self.viewer.load_image(self.current_image_path)
        btn_crop = QPushButton("Crop and Add to List")
        btn_crop.setMinimumHeight(40)
        btn_crop.clicked.connect(self.crop_and_add)
        btn_back = QPushButton("Back")
        btn_back.setMinimumHeight(40)
        btn_back.clicked.connect(self.back_to_select)
        btn_next = QPushButton("Finalize Selection")
        btn_next.setMinimumHeight(40)
        btn_next.clicked.connect(self.finalize_selection)
        btn_next.setEnabled(len(self.cropped_images) > 0)
        btn_add = QPushButton("Add Another Image")
        btn_add.setMinimumHeight(40)
        btn_add.clicked.connect(self.add_another_image)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.viewer)
        layout.addWidget(btn_crop)
        layout.addWidget(btn_add)
        layout.addWidget(btn_next)
        layout.addWidget(btn_back)
        container = QWidget()
        container.setLayout(layout)
        self.layout.addWidget(container)

    def crop_and_add(self):
        cropped = self.viewer.crop_to_clipboard()
        if cropped:
            entry = self.current_selection.copy()
            entry["cropped"] = cropped
            self.cropped_images.append(entry)
            QMessageBox.information(self, "Added", "Cropped image added to list.")

    def add_another_image(self):
        self.step = 0
        self.show_step()

    def finalize_selection(self):
        if not self.cropped_images:
            QMessageBox.warning(self, "No Images", "Please add at least one cropped image.")
            return
        self.step = 2
        self.show_step()

    def back_to_select(self):
        self.step = 0
        self.show_step()

    # Step 3: User Details
    def show_finalize_step(self):
        group = QWidget()
        layout = QFormLayout(group)
        self.name_edit = QLineEdit(self.username)
        self.office_edit = QLineEdit()
        self.date_edit = QLineEdit(datetime.now().strftime('%Y-%m-%d'))
        self.remarks_edit = QTextEdit()
        layout.addRow("Name:", self.name_edit)
        layout.addRow("Office:", self.office_edit)
        layout.addRow("Date:", self.date_edit)
        layout.addRow("Remarks:", self.remarks_edit)
        btn = QPushButton("Next: Header/Footer")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.save_user_details)
        self.layout.addWidget(group)
        self.layout.addWidget(btn)

    def save_user_details(self):
        self.user_details = {
            "name": self.name_edit.text(),
            "office": self.office_edit.text(),
            "date": self.date_edit.text(),
            "remarks": self.remarks_edit.toPlainText()
        }
        self.step = 3
        self.show_step()

    # Step 4: Header/Footer
    def show_header_footer_step(self):
        group = QWidget()
        layout = QFormLayout(group)
        default_header = f"{self.user_details.get('office', '')} | {self.cropped_images[0]['vdc']} | Ward {self.cropped_images[0]['ward']} | Sheet {self.cropped_images[0]['sheet']}"
        default_footer = f"Printed by {self.user_details.get('name', '')} on {self.user_details.get('date', '')} | Page 1"
        self.header_edit = QLineEdit(default_header)
        self.footer_edit = QLineEdit(default_footer)
        layout.addRow("Header:", self.header_edit)
        layout.addRow("Footer:", self.footer_edit)
        btn = QPushButton("Print/Export")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.save_header_footer_and_print_step)
        self.layout.addWidget(group)
        self.layout.addWidget(btn)

    def save_header_footer_and_print_step(self):
        # Save the header/footer text to variables before UI is cleared
        self.header_text = self.header_edit.text()
        self.footer_text = self.footer_edit.text()
        self.step = 4
        self.show_step()

    # Step 5: Print/Export
    def show_print_step(self):
        btn_print = QPushButton("Print")
        btn_print.setMinimumHeight(40)
        btn_print.clicked.connect(self.print_images)
        btn_pdf = QPushButton("Export PDF")
        btn_pdf.setMinimumHeight(40)
        btn_pdf.clicked.connect(self.export_pdf)
        self.layout.addWidget(btn_print)
        self.layout.addWidget(btn_pdf)

    def print_images(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPrinter.A4)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QPrintDialog.Accepted:
            return
        self._print_or_export(printer)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPrinter.A4)
        self._print_or_export(printer)

    def _print_or_export(self, printer):
        painter = QPainter(printer)
        font = QFont(self.font_family, 12)
        painter.setFont(font)
        page_rect = printer.pageRect()
        page = 1
        header_height = 40
        footer_height = 40
        available_height = page_rect.height() - header_height - footer_height

        for entry in self.cropped_images:
            image = entry["cropped"].toImage()
            img_width = image.width()
            img_height = image.height()
            # Scale so the width fits the page width
            scale = page_rect.width() / img_width
            scaled_width = page_rect.width()
            scaled_height = img_height * scale
            y_offset = 0
            while y_offset < img_height:
                painter.save()
                # Header
                painter.drawText(QRectF(0, 0, page_rect.width(), header_height), Qt.AlignCenter, self.header_text)
                # Calculate the height of the part to print on this page
                part_height = min(int(available_height / scale), img_height - y_offset)
                part = image.copy(0, y_offset, img_width, part_height)
                part_scaled = part.scaled(scaled_width, part_height * scale, Qt.IgnoreAspectRatio)
                painter.drawImage(QRectF(0, header_height, scaled_width, part_scaled.height()), part_scaled)
                # Footer
                footer = self.footer_text.replace("Page 1", f"Page {page}")
                painter.drawText(QRectF(0, page_rect.height() - footer_height, page_rect.width(), footer_height), Qt.AlignCenter, footer)
                painter.restore()
                y_offset += part_height
                if y_offset < img_height or entry != self.cropped_images[-1]:
                    printer.newPage()
                    page += 1
        painter.end()
        QMessageBox.information(self, "Done", "Printed/Exported successfully.")

# --- Main Entry Point ---
def main():
    app = QApplication(sys.argv)
    db = UserDB()
    config = Config()
    login = LoginDialog(db)
    if login.exec_() != QDialog.Accepted:
        sys.exit()
    window = MainWindow(db, login.username, login.role, config)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

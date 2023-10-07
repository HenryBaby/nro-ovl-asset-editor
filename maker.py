import os
import sys

from PyQt6.QtCore import QTimer, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QGridLayout,
    QLabel,
)


# Constants
NACP_NAME_SIZE = 0x200
NACP_AUTHOR_SIZE = 0x100
NACP_VERSION_SIZE = 0x10


class Asset:
    def __init__(self, offset):
        self.nacp = bytearray()
        self.icon = bytearray()
        self.romfs = bytearray()
        self.offset = offset

    def load(self, data):
        offset = 0x4 + 0x4

        icon_pos = int.from_bytes(data[offset : offset + 0x8], "little")
        icon_size = int.from_bytes(data[offset + 0x8 : offset + 0x10], "little")
        self.icon += data[icon_pos : icon_pos + icon_size]
        offset += 0x10

        nacp_pos = int.from_bytes(data[offset : offset + 0x8], "little")
        nacp_size = int.from_bytes(data[offset + 0x8 : offset + 0x10], "little")
        self.nacp += data[nacp_pos : nacp_pos + nacp_size]
        offset += 0x10

        romfs_pos = int.from_bytes(data[offset : offset + 0x8], "little")
        romfs_size = int.from_bytes(data[offset + 0x8 : offset + 0x10], "little")
        self.romfs += data[romfs_pos : romfs_pos + romfs_size]
        offset += 0x10

        self.name = self.nacp[0:0x200].decode("utf-8").strip("\x00")
        self.author = self.nacp[0x200:0x300].decode("utf-8").strip("\x00")
        self.version = self.nacp[0x3060:0x3070].decode("utf-8").strip("\x00")

    def updateNACP(self, editor):
        my_name = editor.name.text()
        my_author = editor.author.text()
        my_version = editor.version.text()

        if len(self.nacp) < 0x4000:
            self.nacp += bytearray([0] * (0x4000 - len(self.nacp)))

        for x in range(15):
            app_name = bytearray(my_name, encoding="utf-8")
            app_name += bytearray([0] * (0x200 - len(app_name)))
            self.nacp[x * 0x300 : (x * 0x300 + 0x200)] = app_name

            author = bytearray(my_author, encoding="utf-8")
            author += bytearray([0] * (0x100 - len(author)))
            self.nacp[x * 0x300 + 0x200 : (x * 0x300 + 0x300)] = author

        version = bytearray(my_version, encoding="utf-8")
        version += bytearray([0] * (0x10 - len(version)))
        self.nacp[0x3060 : 0x3060 + 0x10] = version

    def getBytes(self):
        ret = b"ASET"
        ret += bytearray([0, 0, 0, 0])

        offset = 0x38

        icon_size = len(self.icon)

        if icon_size > 0:
            ret += (offset).to_bytes(8, "little")
            ret += (icon_size).to_bytes(8, "little")
        else:
            ret += bytearray([0] * 0x10)
        offset += icon_size

        nacp_size = len(self.nacp)

        if nacp_size > 0:
            ret += (offset).to_bytes(8, "little")
            ret += (nacp_size).to_bytes(8, "little")
        else:
            ret += bytearray([0] * 0x10)
        offset += nacp_size

        romfs_size = len(self.romfs)

        if romfs_size > 0:
            ret += (offset).to_bytes(8, "little")
            ret += (romfs_size).to_bytes(8, "little")
        else:
            ret += bytearray([0] * 0x10)
        offset += romfs_size

        ret += self.icon
        ret += self.nacp
        ret += self.romfs

        return ret


class Editor(QWidget):
    def __init__(self):
        super().__init__()
        layout = QGridLayout()

        self.filename = None
        self.new_image_selected = False

        self.name = QLineEdit("Name")
        self.author = QLineEdit("Author")
        self.version = QLineEdit("Version")

        # Create a default QPixmap with the default image
        self.default_pixmap = QPixmap("default.jpg")

        # Initialize the icon_label with the default image
        self.icon_label = QLabel(self)
        self.icon_label.setPixmap(self.default_pixmap)
        self.icon_label.setFixedSize(256, 256)

        self.data = None
        self.size = 0
        self.asset = None

        self.init_ui()

        # Initialize the flag to track changes
        self.has_changes = False

    def init_ui(self):
        layout = QGridLayout()

        self.style_textboxes([self.name, self.author, self.version])

        self.browse_image_button = QPushButton("Browse Image")
        self.browse_image_button.setDisabled(True)
        self.browse_image_button.clicked.connect(self.browse_image)
        layout.addWidget(self.browse_image_button, 4, 0, 1, 2)

        layout.addWidget(self.name, 0, 0, 1, 2)
        layout.addWidget(self.author, 1, 0, 1, 2)
        layout.addWidget(self.version, 2, 0, 1, 2)

        load_button = QPushButton("Load")
        load_button.clicked.connect(self.browse)
        layout.addWidget(load_button, 3, 0)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_file)

        # Disable the save button initially
        self.save_button.setEnabled(False)

        layout.addWidget(self.save_button, 3, 1)

        layout.addWidget(self.icon_label, 5, 0, 1, 2)

        self.setLayout(layout)

        self.name.textChanged.connect(self.on_field_changed)
        self.author.textChanged.connect(self.on_field_changed)
        self.version.textChanged.connect(self.on_field_changed)

        self.name.setEnabled(False)
        self.author.setEnabled(False)
        self.version.setEnabled(False)

    def on_field_changed(self):
        # Enable the save button when changes are made
        self.has_changes = True
        self.save_button.setEnabled(True)

    def enable_browse_image_button(self):
        self.browse_image_button.setEnabled(True)

    def disable_browse_image_button(self):
        self.browse_image_button.setDisabled(True)

    def change_save_button_label_temporarily(self, label, duration=2000):
        self.save_button.setText(label)
        QTimer.singleShot(duration, self.restore_save_button_label)

    def restore_save_button_label(self):
        self.save_button.setText("Save")

    def style_textboxes(self, textboxes):
        for textbox in textboxes:
            textbox.setStyleSheet("QLineEdit { border: 1px solid #ccc; padding: 3px; }")

    def save_file(self):
        if self.has_changes:
            if self.new_image_selected:
                pixmap = self.icon_label.pixmap()
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "JPG")
                self.asset.icon = byte_array

            self.asset.updateNACP(self)
            asset_bytes = self.asset.getBytes()

            if asset_bytes:
                try:
                    with open(self.filename, "wb") as file:
                        file.write(self.data)
                        file.write(asset_bytes)
                        file.flush()

                    self.change_save_button_label_temporarily(
                        "Saved successfully!", 2000
                    )
                    self.has_changes = False
                    self.save_button.setEnabled(False)
                    return True
                except Exception as e:
                    print(f"Error while saving file: {e}")
            else:
                return False
        else:
            self.save_button.setEnabled(False)

    def browse(self):
        # Add the following line to reset the has_changes flag when loading a file
        self.has_changes = False

        self.filename, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "NRO/OVL Files (*.nro;*.ovl)"
        )

        if self.filename:
            if self.filename.endswith(".nro"):  # Check if it's an .NRO file
                self.enable_browse_image_button()
                # Rest of your code
            else:
                self.disable_browse_image_button()

            with open(self.filename, "rb") as binary:
                self.data = binary.read()
                data = self.data

                # Verify NRO0 format
                if data[0x10:0x14] != b"NRO0":
                    return False

                # Get the filesize, so we can go to the assets section
                self.nrosize = int.from_bytes(data[0x18:0x1C], byteorder="little")
                size = self.nrosize

                # Check for ASET data
                self.asset = Asset(size)
                asset = self.asset
                if len(data) > size + 4 and data[size : size + 0x4] == b"ASET":
                    # Load the asset data
                    self.asset.load(bytearray(data[size:]))

                    self.name.setText(asset.name)
                    self.author.setText(asset.author)
                    self.version.setText(asset.version)

                    self.data = data[:size]

                    # Load and display the image from the asset if available
                    image_data = asset.icon
                    if image_data:
                        pixmap = QPixmap()
                        pixmap.loadFromData(image_data)
                        self.icon_label.setPixmap(pixmap)
                    else:
                        # Load the default image when no icon is available
                        default_pixmap = QPixmap("default.jpg")
                        self.icon_label.setPixmap(default_pixmap)

                self.name.setEnabled(True)
                self.author.setEnabled(True)
                self.version.setEnabled(True)
                self.save_button.setEnabled(False)

    # Inside the Editor class, add the browse_image method
    def browse_image(self):
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tga);;All Files (*)",
        )

        if image_path:
            pixmap = QPixmap(image_path)
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setFixedSize(256, 256)
            self.new_image_selected = (
                True  # Set a flag to indicate a new image is selected
            )

        # Set the flag to indicate a new image is selected
        self.new_image_selected = True
        self.on_field_changed()  # Trigger the change event


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        if getattr(sys, "frozen", False):
            self.icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            self.icon_path = "icon.ico"

        self.setWindowIcon(QIcon(self.icon_path))

        self.setWindowTitle("NOA-E")

        self.editor = Editor()
        self.setCentralWidget(self.editor)

        # Adjust the width of the main window based on widget sizes
        main_window_width = self.editor.sizeHint().width()
        main_window_height = 430  # Set the desired height
        self.setGeometry(100, 100, main_window_width, main_window_height)

        # Set the fixed size of the main window
        self.setFixedSize(self.size())


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

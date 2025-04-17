from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                              QTableWidget, QProgressBar, QLabel, QCheckBox, 
                              QHeaderView, QScrollArea)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
import logging

class GameDataPanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.widget = QWidget()
        self.layout = QVBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(200, 200)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.title_label = QLabel()
        self.tag_label = QLabel()
        self.maker_label = QLabel()
        self.layout.addWidget(self.thumbnail_label)
        self.layout.addWidget(self.title_label)
        self.layout.addWidget(self.tag_label)
        self.layout.addWidget(self.maker_label)
        self.widget.setLayout(self.layout)
        self.setWidget(self.widget)
        self.setWidgetResizable(True)
        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.on_image_downloaded)

    def load_game_data(self, data):
        try:
            self.title_label.setText(data.get('title_kr', data.get('title_jp', 'No Title')))
            self.tag_label.setText(data.get('primary_tag', 'No Tag'))
            self.maker_label.setText(data.get('maker', 'No Maker'))
            thumbnail_url = data.get('thumbnail_url', '')
            logging.debug(f"Loading thumbnail: {thumbnail_url}")
            if thumbnail_url:
                proxy_url = f"https://gamesorter-28083845590.us-central1.run.app/proxy_image/{thumbnail_url}"
                self.network_manager.get(QNetworkRequest(QUrl(proxy_url)))
            else:
                self.thumbnail_label.clear()
                self.thumbnail_label.setText("No Thumbnail")
                logging.warning("No thumbnail URL provided")
        except Exception as e:
            logging.error(f"Load game data error: {e}", exc_info=True)
            self.thumbnail_label.setText("Failed to load data")

    def on_image_downloaded(self, reply):
        try:
            if reply.error():
                logging.error(f"Thumbnail download error: {reply.errorString()}")
                self.thumbnail_label.clear()
                self.thumbnail_label.setText("Failed to load thumbnail")
                return
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            self.thumbnail_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
            logging.debug("Thumbnail loaded successfully")
        except Exception as e:
            logging.error(f"Image download error: {e}", exc_info=True)
            self.thumbnail_label.setText("Failed to load thumbnail")

    def clear_game_data(self):
        self.title_label.setText("No Title")
        self.tag_label.setText("No Tag")
        self.maker_label.setText("No Maker")
        self.thumbnail_label.clear()
        self.thumbnail_label.setText("No Thumbnail")

class MainWindowUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout()
        self.button_layout = QHBoxLayout()
        self.select_folder_btn = QPushButton("폴더 선택")
        self.fetch_data_btn = QPushButton("데이터 가져오기")
        self.rename_btn = QPushButton("이름 변경")
        self.button_layout.addWidget(self.select_folder_btn)
        self.button_layout.addWidget(self.fetch_data_btn)
        self.button_layout.addWidget(self.rename_btn)
        self.main_layout.addLayout(self.button_layout)

        self.select_all_box = QCheckBox("모두 선택")
        self.main_layout.addWidget(self.select_all_box)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["선택", "원본 이름", "제안된 이름"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.main_layout.addWidget(self.table)

        self.progress_bar = QProgressBar()
        self.main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("파일: 0개")
        self.main_layout.addWidget(self.status_label)

        self.log_label = QLabel("상태: 대기 중")
        self.main_layout.addWidget(self.log_label)

        self.game_data_panel = GameDataPanel()
        self.main_layout.addWidget(self.game_data_panel)

        self.setLayout(self.main_layout)
        self.setWindowTitle("게임 압축파일 정리기")
        self.resize(800, 600)
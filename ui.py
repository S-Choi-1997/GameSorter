import sys
import requests
import logging
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QTableWidget, QTableWidgetItem, QCheckBox, 
                               QProgressBar, QHeaderView, QScrollArea)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap

logging.basicConfig(filename="gamesort.log", level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

class GameDataPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.title_label = QLabel("게임 정보")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.title_label)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(200, 200)
        layout.addWidget(self.thumbnail_label)

        self.details_label = QLabel()
        layout.addWidget(self.details_label)

        layout.addStretch()
        self.setLayout(layout)

    def load_game_data(self, data):
        title = data.get('title_kr', data.get('title_jp', '알 수 없음'))
        tags = ', '.join(data.get('tags', ['없음']))
        release_date = data.get('release_date', '알 수 없음')
        rating = data.get('rating', 0.0)
        link = data.get('link', '')
        thumbnail_url = data.get('thumbnail_url', '')

        self.title_label.setText(title)
        details = f"태그: {tags}\n출시일: {release_date}\n평점: {rating}\n링크: {link}"
        self.details_label.setText(details)

        if thumbnail_url:
            try:
                response = requests.get(thumbnail_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    self.thumbnail_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
            except Exception as e:
                logging.error(f"Error loading thumbnail: {e}")
                self.thumbnail_label.setText("썸네일 로드 실패")
        else:
            self.thumbnail_label.setText("썸네일 없음")

    def clear_game_data(self):
        self.title_label.setText("게임 정보")
        self.details_label.setText("")
        self.thumbnail_label.setText("썸네일 없음")

class MainWindowUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameSort")
        self.setGeometry(100, 100, 1200, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # 왼쪽 레이아웃 (테이블 및 컨트롤)
        self.left_layout = QVBoxLayout()

        # 버튼 및 상태 레이블
        self.button_layout = QHBoxLayout()
        self.select_folder_btn = QPushButton("폴더 선택")
        self.select_folder_btn.setFixedSize(100, 30)
        self.button_layout.addWidget(self.select_folder_btn)

        self.fetch_data_btn = QPushButton("게임명 변경")
        self.fetch_data_btn.setFixedSize(100, 30)
        self.fetch_data_btn.setEnabled(False)  # 초기 비활성화
        self.button_layout.addWidget(self.fetch_data_btn)

        self.rename_btn = QPushButton("이름 변경")
        self.rename_btn.setFixedSize(100, 30)
        self.button_layout.addWidget(self.rename_btn)

        self.button_layout.addStretch()
        self.status_label = QLabel("파일: 0개")
        self.button_layout.addWidget(self.status_label)

        self.left_layout.addLayout(self.button_layout)

        # 전체 선택 체크박스
        self.select_all_box = QCheckBox("전체 선택")
        self.select_all_box.setEnabled(False)
        self.left_layout.addWidget(self.select_all_box)

        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["선택", "원본 이름", "제안된 이름"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.left_layout.addWidget(self.table)

        # 로그 및 진행바
        self.log_label = QLabel("로그: 대기 중...")
        self.left_layout.addWidget(self.log_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.left_layout.addWidget(self.progress_bar)

        self.main_layout.addLayout(self.left_layout, 2)

        # 오른쪽 레이아웃 (게임 정보 패널)
        self.right_layout = QVBoxLayout()
        self.game_data_panel = GameDataPanel()
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.game_data_panel)
        scroll_area.setWidgetResizable(True)
        self.right_layout.addWidget(scroll_area)
        self.main_layout.addLayout(self.right_layout, 1)
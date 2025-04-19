from PySide6.QtWidgets import (
    QMainWindow, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QCheckBox, QLabel, QHeaderView, QProgressBar,
    QSplitter, QTextEdit, QSizePolicy, QComboBox, QFormLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
import logging
import requests
import os
import hashlib

logging.basicConfig(filename="gamesort.log", level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

class GameDataPanel(QWidget):
    def __init__(self):
        super().__init__()
        
        self.layout = QVBoxLayout()
        self.cache_dir = "thumbnails"
        
        # 썸네일 레이블
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setMinimumSize(500, 300)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setText("No Thumbnail")
        self.thumbnail_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.layout.addWidget(self.thumbnail_label, alignment=Qt.AlignTop)

        # 제목 레이블
        self.title_label = QLabel("게임 정보")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.layout.addWidget(self.title_label)
        
        #qss
        self.thumbnail_label.setObjectName("thumbnail_label")
        self.title_label.setObjectName("title_label")

        # 정보 표시를 QFormLayout + QLabel로 변경
        self.info_layout = QFormLayout()
        
        self.label_title_kr = QLabel()
        self.label_title_jp = QLabel()
        self.label_rj_code = QLabel()
        self.label_tags = QLabel()
        self.label_release = QLabel()
        self.label_maker = QLabel()
        self.label_platform = QLabel()
        self.label_link = QLabel()
        
        self.info_layout.addRow("제목 (KR):", self.label_title_kr)
        self.info_layout.addRow("제목 (JP):", self.label_title_jp)
        self.info_layout.addRow("RJ 코드:", self.label_rj_code)
        self.info_layout.addRow("태그:", self.label_tags)
        self.info_layout.addRow("출시일:", self.label_release)
        self.info_layout.addRow("제작자:", self.label_maker)
        self.info_layout.addRow("플랫폼:", self.label_platform)
        self.info_layout.addRow("링크:", self.label_link)
        
        info_widget = QWidget()
        info_widget.setLayout(self.info_layout)
        self.layout.addWidget(info_widget)

        # 레이아웃 설정
        self.layout.setStretchFactor(info_widget, 1)
        self.setLayout(self.layout)

    def load_thumbnail_manually(self, url):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            filename = hashlib.sha1(url.encode()).hexdigest() + ".jpg"
            filepath = os.path.join(self.cache_dir, filename)

            if os.path.exists(filepath):
                logging.debug(f"Loading cached thumbnail: {filepath}")
                pixmap = QPixmap()
                if pixmap.load(filepath):
                    self.thumbnail_label.setPixmap(pixmap.scaled(500, 300, Qt.KeepAspectRatio))
                    logging.debug("Cached thumbnail loaded successfully")
                    return
                else:
                    logging.warning(f"Failed to load cached pixmap: {filepath}")
                    os.remove(filepath)

            logging.debug(f"Downloading thumbnail: {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "Referer": "https://www.dlsite.com/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
            }
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200 and response.content:
                pixmap = QPixmap()
                if pixmap.loadFromData(response.content):
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    self.thumbnail_label.setPixmap(pixmap.scaled(300, 300, Qt.KeepAspectRatio))
                    logging.debug("Thumbnail downloaded and cached successfully")
                else:
                    raise Exception("QPixmap loadFromData failed")
            else:
                raise Exception(f"HTTP {response.status_code}, content empty?")
        except Exception as e:
            logging.error(f"Manual thumbnail load error: {e}, URL: {url}")
            self.thumbnail_label.setText("Failed to load thumbnail")

    def load_game_data(self, data):
        try:
            if not data or "error" in data:
                self.label_title_kr.setText("데이터를 불러올 수 없습니다: 데이터가 없거나 오류가 발생했습니다.")
                self.label_title_jp.setText("")
                self.label_rj_code.setText("")
                self.label_tags.setText("")
                self.label_release.setText("")
                self.label_maker.setText("")
                self.label_platform.setText("")
                self.label_link.setText("")
                self.thumbnail_label.setText("No Thumbnail")
                logging.debug("Empty or error data received")
                return

            # 각 QLabel에 데이터 채우기
            self.label_title_kr.setText(data.get('title_kr', 'N/A'))
            self.label_title_jp.setText(data.get('title_jp', 'N/A'))
            self.label_rj_code.setText(data.get('rj_code', 'N/A'))
            
            # ✅ 태그를 버튼 같은 동그란 뱃지로 표시, 연분홍색 고정
            tags = data.get('tags', [])
            if tags:
                tag_color = "#ffdddd"  # 연분홍색 배경
                text_color = "#831f44"  # 텍스트용 진한 분홍색
                
                formatted_tags = []
                for tag in tags:
                    formatted_tags.append(
                        f'<span style="background-color: {tag_color}; color: {text_color}; '
                        f'padding: 4px 8px; border-radius: 12px; margin: 4px; display: inline-block; '
                        f'border: 1px solid {text_color}; font-size: 13px; font-weight: bold; '  # 텍스트 굵게
                        f'box-shadow: 1px 1px 2px #cccccc;">'  # 그림자 추가
                        f'{tag}</span>'
                    )
                
                self.label_tags.setTextFormat(Qt.RichText)
                self.label_tags.setText(' '.join(formatted_tags))
            else:
                self.label_tags.setText("N/A")

            self.label_release.setText(data.get('release_date', 'N/A'))
            self.label_maker.setText(data.get('maker', 'N/A'))
            self.label_platform.setText(data.get('platform', 'N/A'))
            
            # 링크를 클릭 가능하게 처리
            url = data.get('link', 'N/A')
            if url and url != 'N/A':
                self.label_link.setTextFormat(Qt.RichText)
                self.label_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
                self.label_link.setOpenExternalLinks(True)
                self.label_link.setText(f'<a href="{url}" style="color: white;">{url}</a>')
            else:
                self.label_link.setText('N/A')

            thumbnail_url = data.get('thumbnail_url', '')
            logging.debug(f"Loading thumbnail: {thumbnail_url}")
            if thumbnail_url:
                self.load_thumbnail_manually(thumbnail_url)
            else:
                self.thumbnail_label.clear()
                self.thumbnail_label.setText("No Thumbnail")

        except Exception as e:
            logging.error(f"Load game data error: {e}", exc_info=True)
            self.label_title_kr.setText("데이터 로드 실패: 오류 발생")
            self.label_title_jp.setText("")
            self.label_rj_code.setText("")
            self.label_tags.setText("")
            self.label_release.setText("")
            self.label_maker.setText("")
            self.label_platform.setText("")
            self.label_link.setText("")
            self.thumbnail_label.setText("Failed to load thumbnail")

    def clear_game_data(self):
        self.label_title_kr.setText("선택된 게임이 없습니다.")
        self.label_title_jp.setText("")
        self.label_rj_code.setText("")
        self.label_tags.setText("")
        self.label_release.setText("")
        self.label_maker.setText("")
        self.label_platform.setText("")
        self.label_link.setText("")
        self.thumbnail_label.clear()
        self.thumbnail_label.setText("No Thumbnail")

class MainWindowUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("게임 파일 정리기")
        self.setGeometry(100, 100, 1600, 900)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        button_layout = QHBoxLayout()
        self.select_folder_btn = QPushButton("📁 폴더 선택")
        self.fetch_data_btn = QPushButton("🔄 게임 데이터 로드")
        self.rename_btn = QPushButton("💾 이름 변경")
        self.remove_tag_btn = QPushButton("🧹 태그 제거")
        button_layout.addWidget(self.select_folder_btn)
        button_layout.addWidget(self.fetch_data_btn)
        button_layout.addWidget(self.rename_btn)
        button_layout.addWidget(self.remove_tag_btn)
        left_layout.addLayout(button_layout)
        
        button_height = 40  # 원하는 높이로 조절
        self.select_folder_btn.setFixedHeight(button_height)
        self.fetch_data_btn.setFixedHeight(button_height)
        self.rename_btn.setFixedHeight(button_height)
        self.remove_tag_btn.setFixedHeight(button_height)

        self.table = QTableWidget(0, 4)  # 열 수를 3에서 4로 변경
        self.table.setHorizontalHeaderLabels(["선택", "원래 이름", "제안된 이름", "태그 선택"])
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(3, 100)  # 태그 선택 열 너비 설정
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)  # 태그 선택 열은 고정 너비
        left_layout.addWidget(self.table)

        status_layout = QHBoxLayout()
        self.select_all_box = QCheckBox("전체 선택")
        self.status_label = QLabel("파일: 0개")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        status_layout.addWidget(self.select_all_box)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        left_layout.addLayout(status_layout)

        self.log_label = QLabel("대기 중입니다.")
        self.log_label.setWordWrap(True)
        self.log_label.setMaximumWidth(self.table.width())
        self.log_label.setMinimumHeight(50)
        left_layout.addWidget(self.log_label)
        
        self.select_folder_btn.setObjectName("select_folder_btn")
        self.fetch_data_btn.setObjectName("fetch_data_btn")
        self.rename_btn.setObjectName("rename_btn")
        self.remove_tag_btn.setObjectName("remove_tag_btn")
        self.log_label.setObjectName("log_label")
        self.status_label.setObjectName("status_label")

        self.game_data_panel = GameDataPanel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self.game_data_panel)
        splitter.setSizes([800, 400])
        main_layout.addWidget(splitter)
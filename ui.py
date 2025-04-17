from PySide6.QtWidgets import (
    QMainWindow, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QCheckBox, QLabel, QHeaderView, QProgressBar,
    QSplitter, QTextEdit
)
from PySide6.QtCore import Qt

class GameDataPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()
        self.title_label = QLabel("게임 정보")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.layout.addWidget(self.title_label)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.layout.addWidget(self.info_text)
        self.setLayout(self.layout)

    def load_game_data(self, data):
        if "error" in data:
            self.info_text.setText("데이터를 불러올 수 없습니다.")
            return

        info = f"제목 (KR): {data.get('title_kr', 'N/A')}\n"
        info += f"제목 (JP): {data.get('title_jp', 'N/A')}\n"
        info += f"RJ 코드: {data.get('rj_code', 'N/A')}\n"
        info += f"태그: {', '.join(data.get('tags', []))}\n"
        info += f"출시일: {data.get('release_date', 'N/A')}\n"
        info += f"제작자: {data.get('maker', 'N/A')}\n"
        info += f"플랫폼: {data.get('platform', 'N/A')}\n"
        info += f"링크: {data.get('link', 'N/A')}"
        self.info_text.setText(info)

    def clear_game_data(self):
        self.info_text.setText("선택된 게임이 없습니다.")

class MainWindowUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("게임 파일 정리기")
        self.setGeometry(100, 100, 1200, 600)

        # 메인 위젯 및 레이아웃
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # 왼쪽 패널 (테이블 및 컨트롤)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        self.select_folder_btn = QPushButton("📁 폴더 선택")
        self.fetch_data_btn = QPushButton("🔄 게임명 변경")
        self.rename_btn = QPushButton("💾 이름 변경")
        button_layout.addWidget(self.select_folder_btn)
        button_layout.addWidget(self.fetch_data_btn)
        button_layout.addWidget(self.rename_btn)
        left_layout.addLayout(button_layout)

        # 테이블
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["선택", "원래 이름", "제안된 이름"])
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        left_layout.addWidget(self.table)

        # 하단 상태 레이아웃
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

        # 로그 레이블
        self.log_label = QLabel("대기 중입니다.")
        self.log_label.setWordWrap(True)  # 줄바꿈 활성화
        self.log_label.setMaximumWidth(self.table.width())  # 테이블 너비에 맞춤
        self.log_label.setMinimumHeight(50)  # 최소 높이 설정
        left_layout.addWidget(self.log_label)

        # 오른쪽 패널 (게임 정보)
        self.game_data_panel = GameDataPanel()

        # 스플리터로 좌우 패널 분할
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self.game_data_panel)
        splitter.setSizes([800, 400])
        main_layout.addWidget(splitter)
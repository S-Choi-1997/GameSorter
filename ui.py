import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QCheckBox, QHBoxLayout, QLabel, QHeaderView,
    QMessageBox, QProgressBar, QLineEdit, QTextEdit, QSplitter, QGroupBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from core import MainWindowLogic
from game_data import GameDataPanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("게임 압축파일 정리기 - AI 모드")
        self.setGeometry(100, 100, 1200, 800)

        # 로직 초기화
        self.logic = MainWindowLogic(self)
        self.game_data_panel = GameDataPanel(self)

        # 메인 위젯
        main_widget = QWidget()
        main_layout = QHBoxLayout()

        # 스플리터로 수평 2분할: (1+2번 칸)과 (3번 칸)
        splitter = QSplitter(Qt.Horizontal)

        # 1+2번 칸: 상단(컨트롤 상단) + 중앙(테이블) + 하단(컨트롤 하단)
        left_center_widget = QWidget()
        left_center_layout = QVBoxLayout()

        # 컨트롤 상단: 폴더 선택, AI 분석, 재분석, API 키 입력, 로그
        control_upper_widget = QWidget()
        control_upper_layout = QVBoxLayout()

        # 상단 버튼 (폴더 선택, AI 분석, 재분석)
        top_layout = QHBoxLayout()
        self.select_btn = QPushButton("\U0001F4C1 폴더 선택")
        self.analyze_btn = QPushButton("\U0001F9E0 AI 분석 실행")
        self.reanalyze_btn = QPushButton("\U0001F504 선택 항목 재분석")
        top_layout.addWidget(self.select_btn)
        top_layout.addWidget(self.analyze_btn)
        top_layout.addWidget(self.reanalyze_btn)

        # API 키 입력
        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("OpenAI API 키 입력")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_toggle = QPushButton("👁️")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.setFixedWidth(30)
        api_key_layout.addWidget(QLabel("API 키:"))
        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.api_key_toggle)

        # 로그
        self.log_label = QLabel("대기 중입니다.")

        # 컨트롤 상단 레이아웃 구성
        control_upper_layout.addLayout(top_layout)
        control_upper_layout.addLayout(api_key_layout)
        control_upper_layout.addWidget(self.log_label)
        control_upper_widget.setLayout(control_upper_layout)

        # 테이블: 1, 2번 칸 전체를 차지
        table_widget = QWidget()
        table_layout = QVBoxLayout()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["선택", "원래 이름", "제안 이름"])
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.cellClicked.connect(self.logic.on_table_cell_clicked)
        table_layout.addWidget(self.table)
        table_widget.setLayout(table_layout)

        # 컨트롤 하단: 전체 선택, 상태, 진행바, 변환 실행, 태그 입력
        control_lower_widget = QWidget()
        control_lower_layout = QVBoxLayout()

        # 하단 컨트롤 (전체 선택, 상태, 진행바, 변환 실행)
        bottom_layout = QHBoxLayout()
        self.select_all_box = QCheckBox("전체 선택")
        self.status_label = QLabel("파일: 0개")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.rename_btn = QPushButton("\U0001F4C1 변환 실행")
        bottom_layout.addWidget(self.select_all_box)
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.rename_btn)

        # 태그 입력
        tag_layout = QHBoxLayout()
        self.engine_input = QLineEdit()
        self.engine_input.setPlaceholderText("엔진 태그 입력 (예: 쯔꾸르)")
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("세부 태그 입력 (예: NTR, RPG 등)")
        self.tag_apply_btn = QPushButton("선택 항목 태그 수정")
        tag_layout.addWidget(self.engine_input)
        tag_layout.addWidget(self.tag_input)
        tag_layout.addWidget(self.tag_apply_btn)

        # 컨트롤 하단 레이아웃 구성
        control_lower_layout.addLayout(bottom_layout)
        control_lower_layout.addLayout(tag_layout)
        control_lower_widget.setLayout(control_lower_layout)

        # 1+2번 칸에 상단(컨트롤 상단), 중앙(테이블), 하단(컨트롤 하단) 배치
        left_center_layout.addWidget(control_upper_widget)
        left_center_layout.addWidget(table_widget)
        left_center_layout.addWidget(control_lower_widget)
        left_center_widget.setLayout(left_center_layout)
        splitter.addWidget(left_center_widget)

        # 3번 칸: 게임 정보 패널
        game_data_widget = QGroupBox("게임 정보")
        game_data_layout = QVBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(200, 200)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.title_label = QLabel("제목: ")
        self.release_date_label = QLabel("출시일: ")
        self.translated_label = QLabel("번역 상태: ")
        self.tags_label = QTextEdit()
        self.tags_label.setReadOnly(True)
        self.tags_label.setFixedHeight(100)
        game_data_layout.addWidget(self.thumbnail_label)
        game_data_layout.addWidget(self.title_label)
        game_data_layout.addWidget(self.release_date_label)
        game_data_layout.addWidget(self.translated_label)
        game_data_layout.addWidget(QLabel("태그:"))
        game_data_layout.addWidget(self.tags_label)
        game_data_widget.setLayout(game_data_layout)
        splitter.addWidget(game_data_widget)

        # 스플리터 크기 비율: 1+2번 칸(800), 3번 칸(400)
        splitter.setSizes([800, 400])
        main_layout.addWidget(splitter)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # 이벤트 연결
        self.select_btn.clicked.connect(self.logic.select_folder)
        self.analyze_btn.clicked.connect(self.logic.analyze_with_ai)
        self.reanalyze_btn.clicked.connect(self.logic.reanalyze_selected)
        self.rename_btn.clicked.connect(self.logic.rename_files)
        self.select_all_box.toggled.connect(self.logic.toggle_all_selection)
        self.tag_apply_btn.clicked.connect(self.logic.apply_tag_edit)
        self.api_key_toggle.clicked.connect(self.toggle_api_key_visibility)

    def toggle_api_key_visibility(self):
        if self.api_key_toggle.isChecked():
            self.api_key_input.setEchoMode(QLineEdit.Normal)
            self.api_key_toggle.setText("🙈")
        else:
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.api_key_toggle.setText("👁️")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
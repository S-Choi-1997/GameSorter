import os
import re
import json
import requests
from bs4 import BeautifulSoup
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QCheckBox
from PySide6.QtCore import Qt
import logging
from ui import MainWindowUI

logging.basicConfig(filename="gamesort.log", level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

class MainWindowLogic(MainWindowUI):
    def __init__(self):
        super().__init__()
        self.results = []
        self.cache_file = "dlsite_cache.json"
        self.cache = self.load_cache()
        self.folder_path = None
        # 실제 Cloud Run URL로 변경해야 함
        # 예: https://game-sort-service-xxx.a.run.app (Google Cloud Console에서 확인)
        self.SERVER_URL = "https://rj-server-xxx.a.run.app"

        # UI 이벤트 연결
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.fetch_data_btn.clicked.connect(self.fetch_game_data_and_update)
        self.rename_btn.clicked.connect(self.rename_files)
        self.select_all_box.stateChanged.connect(self.toggle_all_selection)
        self.table.cellClicked.connect(self.on_table_cell_clicked)

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            logging.info("No cache file found, starting with empty cache")
            return {}
        except Exception as e:
            self.log_label.setText(f"캐시 로드 오류: {str(e)}")
            logging.error(f"Cache load error: {str(e)}")
            return {}

    def save_cache(self, data):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logging.info("Cache saved successfully")
        except Exception as e:
            self.log_label.setText(f"캐시 저장 오류: {str(e)}")
            logging.error(f"Cache save error: {str(e)}")

    def fetch_game_data(self, items):
        try:
            logging.debug(f"Sending request to {self.SERVER_URL}/games with items: {items}")
            response = requests.post(
                f"{self.SERVER_URL}/games",
                json={"items": items},
                timeout=10
            )
            logging.debug(f"Server response status: {response.status_code}")
            logging.debug(f"Server response content: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                self.log_label.setText(f"서버 오류: 상태 코드 {response.status_code} - {response.text}")
                logging.error(f"Server fetch failed: Status {response.status_code} - {response.text}")
                return []
        except requests.exceptions.RequestException as e:
            self.log_label.setText(f"서버 요청 실패: {str(e)}")
            logging.error(f"Server fetch error: {str(e)}")
            return []

    def fetch_game_data_and_update(self):
        if not self.results:
            self.log_label.setText("먼저 폴더를 선택하세요.")
            return

        self.log_label.setText("서버에서 데이터 가져오는 중...")
        items = []
        for result in self.results:
            original = result['original']
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            if rj_match:
                rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '')
                items.append(rj_code)
            else:
                items.append(original)

        game_data = self.fetch_game_data(items)
        if not game_data:
            self.log_label.setText("데이터 가져오기 실패")
            return

        # 데이터 갱신
        for result, data in zip(self.results, game_data):
            result['game_data'] = data
            if "error" not in data:
                tag = data.get('tags', ['기타'])[0]
                title = data.get('title_kr', result['original'])
                result['suggested'] = f"[{data.get('rj_code', data.get('title', '기타'))}][{tag}]{title}"

        # 테이블 갱신
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 2, QTableWidgetItem(self.results[row]['suggested']))
        self.table.setUpdatesEnabled(True)
        self.log_label.setText("게임명 변경 완료")

    def select_folder(self):
        self.folder_path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not self.folder_path:
            logging.info("No folder selected")
            self.log_label.setText("폴더 선택 취소됨")
            return

        self.log_label.setText("폴더 스캔 중...")
        logging.info(f"Scanning folder: {self.folder_path}")
        self.table.setRowCount(0)
        self.results.clear()

        # 폴더 내 파일 목록 가져오기
        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]
        files.sort()

        if not files:
            self.log_label.setText("폴더에 파일이 없습니다.")
            self.status_label.setText("파일: 0개")
            self.fetch_data_btn.setEnabled(False)
            return

        # 테이블에 파일 목록 표시
        self.table.setUpdatesEnabled(False)
        for idx, original in enumerate(files):
            suggested = original

            result = {
                'original': original,
                'suggested': suggested,
                'path': os.path.join(self.folder_path, original),
                'game_data': {}
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.table.insertRow(idx)
            self.table.setCellWidget(idx, 0, chk)
            self.table.setItem(idx, 1, QTableWidgetItem(original))
            self.table.setItem(idx, 2, QTableWidgetItem(suggested))
            logging.debug(f"Added row {idx}: {original}")

        self.table.setUpdatesEnabled(True)
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
        self.fetch_data_btn.setEnabled(True)
        self.update_select_all_state()

    def on_checkbox_changed(self, row, checked):
        logging.debug(f"Checkbox changed: row={row}, checked={checked}")
        self.update_select_all_state()

    def on_table_cell_clicked(self, row, column):
        data = self.results[row]['game_data']
        if not data:
            self.game_data_panel.clear_game_data()
            return

        self.game_data_panel.load_game_data(data)

    def update_select_all_state(self):
        if self.table.rowCount() == 0:
            self.select_all_box.blockSignals(True)
            self.select_all_box.setChecked(False)
            self.select_all_box.setEnabled(False)
            self.select_all_box.blockSignals(False)
            return

        all_checked = True
        none_checked = True
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if chk.isChecked():
                none_checked = False
            else:
                all_checked = False

        self.select_all_box.blockSignals(True)
        self.select_all_box.setEnabled(True)
        if all_checked:
            self.select_all_box.setChecked(True)
        elif none_checked:
            self.select_all_box.setChecked(False)
        else:
            self.select_all_box.setTristate(True)
            self.select_all_box.setCheckState(Qt.CheckState.PartiallyChecked)
        self.select_all_box.blockSignals(False)

    def toggle_all_selection(self, state):
        checked = state == Qt.Checked
        self.log_label.setText("전체 선택 상태 변경 중...")
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            chk.setChecked(checked)
        self.table.setUpdatesEnabled(True)
        self.log_label.setText(f"전체 선택 {'완료' if checked else '해제'}")
        self.update_select_all_state()

    def get_unique_path(self, new_path):
        base, ext = os.path.splitext(new_path)
        counter = 1
        while os.path.exists(new_path):
            new_path = f"{base}_{counter}{ext}"
            counter += 1
        return new_path

    def rename_files(self):
        total = self.table.rowCount()
        self.progress_bar.setValue(0)
        self.log_label.setText("파일 이름 변경 중...")
        completed = 0
        errors = []

        for row in range(total):
            self.progress_bar.setValue(int((row + 1) / total * 100))
            chk = self.table.cellWidget(row, 0)
            if not chk.isChecked():
                continue

            original_path = self.results[row]['path']
            original_name = os.path.basename(original_path)
            new_name = self.results[row]['suggested']

            if new_name == original_name or '[오류]' in new_name:
                continue

            new_path = os.path.join(self.folder_path, new_name)
            new_path = self.get_unique_path(new_path)

            try:
                self.log_label.setText(f"이름 변경: {original_name} → {new_name}")
                os.rename(original_path, new_path)
                self.results[row]['path'] = new_path
                completed += 1
                self.status_label.setText(f"파일: {total}개")
                logging.info(f"Renamed: {original_name} -> {new_name}")
            except Exception as e:
                errors.append(f"{original_path}: {e}")
                logging.error(f"Rename error: {original_path}: {str(e)}")

        self.progress_bar.setValue(100)
        if errors:
            QMessageBox.warning(self, "오류", f"다음 파일 이름 변경 실패:\n" + "\n".join(errors[:5]))
        self.log_label.setText(f"이름 변경 완료: {completed}개 파일 변경됨.")
        self.update_select_all_state()

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindowLogic()
    window.show()
    sys.exit(app.exec())
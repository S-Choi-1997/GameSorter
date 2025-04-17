import os
import re
import json
import requests
import time
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QCheckBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication
import logging
import tenacity
from ui import MainWindowUI

logging.basicConfig(filename="gamesort.log", level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

class FetchWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, server_url, items):
        super().__init__()
        self.server_url = server_url
        self.items = items
        self.task_id = None

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying request (attempt {retry_state.attempt_number}/5) after {retry_state.next_action.sleep} seconds"
        )
    )
    def make_request(self, url, method='post', json_data=None):
        if method == 'post':
            return requests.post(url, json=json_data, timeout=30)
        return requests.get(url, timeout=10)

    def run(self):
        try:
            total_items = len(self.items)
            if total_items == 0:
                self.log.emit("처리할 파일이 없습니다.")
                self.result.emit([])
                return

            self.log.emit(f"총 {total_items}개 파일 처리 시작")
            logging.info(f"Starting fetch for {total_items} items")

            response = self.make_request(f"{self.server_url}/games", method='post', json_data={"items": self.items})
            logging.debug(f"Server response status: {response.status_code}")
            logging.debug(f"Server response content: {response.text}")

            if response.status_code != 200:
                self.error.emit(f"서버 오류: 상태 코드 {response.status_code} - {response.text}")
                return

            response_data = response.json()
            self.task_id = response_data.get("task_id")
            game_data = response_data.get("results")

            if not self.task_id:
                self.result.emit(game_data)
                self.progress.emit(100)
                self.log.emit("데이터 가져오기 완료")
                return

            timeout = 600  # 10분 타임아웃
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    progress_response = self.make_request(f"{self.server_url}/progress/{self.task_id}", method='get')
                    if progress_response.status_code != 200:
                        self.error.emit(f"진행 상황 조회 실패: {progress_response.text}")
                        return

                    progress = progress_response.json()
                    completed = progress.get("completed", 0)
                    total = progress.get("total", total_items)
                    status = progress.get("status", "processing")

                    percentage = int((completed / total) * 100)
                    self.progress.emit(percentage)
                    self.log.emit(f"처리 중: {completed}/{total} ({percentage}%)")

                    if status == "completed":
                        break
                    time.sleep(2)
                except requests.exceptions.RequestException as e:
                    logging.warning(f"Progress request failed: {e}, retrying...")

            if status != "completed":
                self.error.emit("작업이 타임아웃되었습니다")
                return

            self.result.emit(game_data)
            self.progress.emit(100)
            self.log.emit("데이터 가져오기 완료")
        except Exception as e:
            self.error.emit(f"서버 요청 실패: {str(e)}")
            logging.error(f"FetchWorker error: {str(e)}", exc_info=True)
        finally:
            self.finished.emit()

class MainWindowLogic(MainWindowUI):
    def __init__(self):
        super().__init__()
        self.results = []
        self.cache_file = "dlsite_cache.json"
        self.cache = self.load_cache()
        self.folder_path = None
        self.SERVER_URL = "https://gamesorter-28083845590.us-central1.run.app"
        self.worker = None

        # UI 이벤트 연결
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.fetch_data_btn.clicked.connect(self.fetch_game_data_and_update)
        self.rename_btn.clicked.connect(self.rename_files)
        self.select_all_box.stateChanged.connect(self.toggle_all_selection)
        self.table.cellClicked.connect(self.on_table_cell_clicked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.log_label.setMaximumWidth(self.table.width())

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

    def fetch_game_data_and_update(self):
        if not self.results:
            self.log_label.setText("먼저 폴더를 선택하세요.")
            QMessageBox.warning(self, "경고", "폴더를 선택하세요.")
            return

        self.log_label.setText("서버에서 데이터 가져오는 중...")
        self.progress_bar.setValue(0)
        self.fetch_data_btn.setEnabled(False)

        items = []
        for result in self.results:
            original = result['original']
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            if rj_match:
                rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '')
                items.append(rj_code)
            else:
                items.append(original)

        self.worker = FetchWorker(self.SERVER_URL, items)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_label.setText)
        self.worker.result.connect(self.on_fetch_finished)
        self.worker.error.connect(self.on_fetch_error)
        self.worker.finished.connect(self.on_fetch_finished_cleanup)
        self.worker.start()

    def on_fetch_finished(self, game_data):
        try:
            if not game_data:
                self.log_label.setText("데이터 가져오기 실패")
                QMessageBox.warning(self, "오류", "데이터를 가져오지 못했습니다.")
                return

            error_count = 0
            self.table.setUpdatesEnabled(False)
            for row, (result, data) in enumerate(zip(self.results, game_data)):
                result['game_data'] = data
                if "error" in data:
                    logging.warning(f"Error for {data.get('rj_code', data.get('title', 'Unknown'))}: {data['error']}")
                    result['suggested'] = f"[기타][기타]{result['original']}"
                    error_count += 1
                    self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))
                    continue

                rj_code = data.get('rj_code', '기타')
                tag = data.get('primary_tag', '기타')
                title = data.get('title_kr', data.get('title_jp', result['original']))
                maker = data.get('maker', '')

                title = re.sub(rf"\b{rj_code}\b", "", title, flags=re.IGNORECASE).strip()
                title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')
                maker_tag = f"[{maker}]" if maker else ""
                result['suggested'] = f"[{rj_code}][{tag}]{maker_tag}{title}"
                logging.debug(f"Processed {rj_code or title}: thumbnail_url={data.get('thumbnail_url', 'None')}")

                self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

            self.table.setUpdatesEnabled(True)
            self.log_label.setText(f"게임명 변경 완료, {error_count}개 항목 실패")
            if error_count > 0:
                QMessageBox.warning(self, "경고", f"{error_count}개 항목을 처리하지 못했습니다. 로그를 확인하세요.")
            if error_count == len(self.results):
                QMessageBox.warning(self, "경고", "모든 항목을 처리하지 못했습니다. RJ 코드가 유효한지 확인하세요.")
        except Exception as e:
            logging.error(f"on_fetch_finished error: {e}", exc_info=True)
            self.log_label.setText("데이터 처리 중 오류 발생")
            QMessageBox.critical(self, "오류", f"데이터 처리 중 오류: {str(e)}")

    def on_fetch_error(self, error_msg):
        max_length = 100
        if len(error_msg) > max_length:
            error_msg = error_msg[:max_length] + "... (자세한 내용은 로그를 확인하세요)"
        self.log_label.setText(error_msg)
        self.progress_bar.setValue(0)
        QMessageBox.warning(self, "오류", error_msg)

    def on_fetch_finished_cleanup(self):
        self.fetch_data_btn.setEnabled(True)
        self.worker = None

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

        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]
        files.sort()

        if not files:
            self.log_label.setText("폴더에 파일이 없습니다.")
            self.status_label.setText("파일: 0개")
            self.fetch_data_btn.setEnabled(False)
            return

        self.table.setUpdatesEnabled(False)
        for idx, original in enumerate(files):
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            suggested = f"[{rj_code}][기타]{original}" if rj_match else f"[기타][기타]{original}"

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
        try:
            data = self.results[row]['game_data']
            if not data or "error" in data:
                self.game_data_panel.clear_game_data()
                return
            self.game_data_panel.load_game_data(data)
        except Exception as e:
            logging.error(f"Table cell clicked error: {e}", exc_info=True)
            self.log_label.setText("게임 데이터 로드 중 오류")

    def update_select_all_state(self):
        try:
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
        except Exception as e:
            logging.error(f"Update select all state error: {e}", exc_info=True)

    def toggle_all_selection(self, state):
        try:
            checked = state == Qt.Checked
            self.log_label.setText("전체 선택 상태 변경 중...")
            self.table.setUpdatesEnabled(False)
            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                chk.setChecked(checked)
            self.table.setUpdatesEnabled(True)
            self.log_label.setText(f"전체 선택 {'완료' if checked else '해제'}")
            self.update_select_all_state()
        except Exception as e:
            logging.error(f"Toggle all selection error: {e}", exc_info=True)
            self.log_label.setText("전체 선택 처리 중 오류")

    def get_unique_path(self, new_path):
        base, ext = os.path.splitext(new_path)
        counter = 1
        while os.path.exists(new_path):
            new_path = f"{base}_{counter}{ext}"
            counter += 1
        return new_path

    def rename_files(self):
        try:
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
        except Exception as e:
            logging.error(f"Rename files error: {e}", exc_info=True)
            self.log_label.setText("파일 이름 변경 중 오류")
            QMessageBox.critical(self, "오류", f"파일 이름 변경 중 오류: {str(e)}")

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = MainWindowLogic()
    window.show()
    sys.exit(app.exec())
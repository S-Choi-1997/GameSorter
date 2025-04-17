import os
import re
import json
import requests
from bs4 import BeautifulSoup
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

    def __init__(self, server_url, items, cache_file="dlsite_cache.json"):
        super().__init__()
        self.server_url = server_url
        self.items = items
        self.cache_file = cache_file
        self.cache = self.load_cache()

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            logging.info("No cache file found, starting with empty cache")
            return {}
        except Exception as e:
            logging.error(f"Cache load error: {e}")
            return {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            logging.info("Cache saved successfully")
        except Exception as e:
            logging.error(f"Cache save error: {e}")

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying request (attempt {retry_state.attempt_number}/3) after {retry_state.next_action.sleep} seconds"
        )
    )
    def get_dlsite_data(self, rj_code):
        import time
        if rj_code in self.cache:
            logging.info(f"Local cache hit for {rj_code}")
            return self.cache[rj_code]

        url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'

        if response.status_code != 200:
            raise Exception(f"DLsite fetch failed: Status {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')
        title_tag = soup.find('h1', id='work_name') or soup.find('h1', itemprop='name')
        title_jp = title_tag.text.strip() if title_tag else (soup.find('meta', property='og:title')['content'].strip() if soup.find('meta', property='og:title') else rj_code)

        tags_jp = []
        genre_elements = soup.find_all('a', href=lambda x: x and '/maniax/genre' in x)
        for elem in genre_elements:
            tag = elem.text.strip()
            if tag:
                tags_jp.append(tag)

        maker = soup.find('span', class_='maker_name')
        maker = maker.text.strip() if maker else ""

        release_date = soup.find('th', text=re.compile('販売日')) or soup.find('th', text=re.compile('Release date'))
        release_date = release_date.find_next('td').text.strip() if release_date else "N/A"

        thumbnail = soup.find('meta', property='og:image')
        thumbnail_url = thumbnail['content'] if thumbnail else ""

        data = {
            'rj_code': rj_code,
            'title_jp': title_jp,
            'tags_jp': tags_jp,
            'release_date': release_date,
            'thumbnail_url': thumbnail_url,
            'maker': maker,
            'link': url,
            'platform': 'rj',
            'rating': 0.0,
            'timestamp': time.time()
        }
        self.cache[rj_code] = data
        self.save_cache()
        logging.info(f"Fetched DLsite data for {rj_code}")
        return data

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying server request (attempt {retry_state.attempt_number}/5) after {retry_state.next_action.sleep} seconds"
        )
    )
    def make_request(self, url, method='post', json_data=None):
        logging.debug(f"Sending {method.upper()} request to {url} with data: {json_data}")
        try:
            if method == 'post':
                response = requests.post(url, json=json_data, timeout=30)
            else:
                response = requests.get(url, timeout=10)
            logging.debug(f"Received response: status={response.status_code}, content={response.text[:1000]}")
            response.raise_for_status()
            return response
        except Exception as e:
            logging.error(f"Request failed: {e}")
            raise

    def run(self):
        try:
            total_items = len(self.items)
            if total_items == 0:
                self.log.emit("처리할 파일이 없습니다.")
                self.result.emit([])
                return

            self.log.emit(f"총 {total_items}개 파일 처리 시작")
            logging.info(f"Starting fetch for {total_items} items: {self.items}")

            # 1. Firestore 캐시 확인
            response = self.make_request(f"{self.server_url}/games", method='post', json_data={"items": self.items})
            response_data = response.json()
            results = response_data.get("results", [])
            missing = response_data.get("missing", [])
            self.task_id = response_data.get("task_id")

            # 2. Firestore에 없는 항목만 로컬 크롤링
            local_results = []
            for i, item in enumerate(missing):
                rj_match = re.match(r'^[Rr][Jj]\d{6,8}$', item, re.IGNORECASE)
                if rj_match:
                    rj_code = rj_match.group(0).upper()
                    try:
                        data = self.get_dlsite_data(rj_code)
                        local_results.append(data)
                    except Exception as e:
                        logging.error(f"Local crawl failed for {rj_code}: {e}")
                        local_results.append({'error': f'Game not found for {rj_code}', 'platform': 'rj', 'rj_code': rj_code})
                else:
                    local_results.append({
                        'title': item,
                        'title_kr': item,
                        'primary_tag': "기타",
                        'tags': ["기타"],
                        'thumbnail_url': '',
                        'platform': 'steam',
                        'timestamp': time.time()
                    })
                self.progress.emit(int((i + 1) / len(missing) * 50))
                self.log.emit(f"로컬 크롤링: {item} ({i + 1}/{len(missing)})")

            # 3. 로컬 크롤링 결과를 app.py로 보내 번역 및 저장
            if local_results:
                response = self.make_request(f"{self.server_url}/games", method='post', json_data={"items": local_results})
                response_data = response.json()
                translated_results = response_data.get("results", [])
                results.extend(translated_results)  # 번역된 결과 추가

            # 4. 최종 결과 반환
            self.result.emit(results)
            self.progress.emit(100)
            self.log.emit("데이터 가져오기 완료")
        except Exception as e:
            self.error.emit(f"작업 실패: {str(e)}")
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

    def save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            logging.info("Cache saved successfully")
        except Exception as e:
            self.log_label.setText(f"캐시 저장 오류: {str(e)}")
            logging.error(f"Cache save error: {str(e)}")

    def fetch_game_data_and_update(self):
        if not self.results:
            self.log_label.setText("먼저 폴더를 선택하세요.")
            QMessageBox.warning(self, "경고", "폴더를 선택하세요.")
            return

        self.log_label.setText("Firestore에서 데이터 확인 중...")
        self.progress_bar.setValue(0)
        self.fetch_data_btn.setEnabled(False)

        items = []
        for result in self.results:
            rj_code = result.get('rj_code', '')
            if rj_code:
                items.append(rj_code)
            else:
                items.append(result['original'])

        self.worker = FetchWorker(self.SERVER_URL, items, self.cache_file)
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
                rj_code = result.get('rj_code') or data.get('rj_code') or "기타"
                original_title = result.get('original_title', '')

                if "error" in data or not data:
                    logging.warning(f"Error for {data.get('rj_code', data.get('title', 'Unknown'))}: {data.get('error', 'No data')}")
                    result['suggested'] = f"[{rj_code}][기타] {result['original']}"
                    error_count += 1
                    self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))
                    continue

                tag = data.get('primary_tag') or "기타"
                title_kr = data.get('title_kr')
                title_jp = data.get('title_jp', result.get('original', ''))

                # 제목 우선순위: title_kr > original_title > title_jp
                title = title_kr or original_title or title_jp or ''
                title = re.sub(rf"\b{rj_code}\b", "", title, flags=re.IGNORECASE).strip()
                title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')

                # 최종 이름 조합: [RJ코드][태그] 제목
                result['suggested'] = f"[{rj_code}][{tag}] {title}"
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
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else ''
            
            # RJ 코드 제거 후 원래 제목 추출
            original_title = re.sub(rf"[Rr][Jj][_\-\s]?\d{{6,8}}", "", original, re.IGNORECASE).strip('_').strip()
            original_title = original_title if original_title and original_title != os.path.splitext(original)[1] else ''
            
            suggested = f"[{rj_code or '기타'}][기타]{original}"

            result = {
                'original': original,
                'original_title': original_title,
                'rj_code': rj_code,
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
            logging.debug(f"Added row {idx}: {original}, original_title={original_title}")

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
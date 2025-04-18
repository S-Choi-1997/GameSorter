import os
import re
import json
import requests
import time
from bs4 import BeautifulSoup
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QCheckBox, QComboBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication
import logging
import tenacity
from ui import MainWindowUI
from urllib.parse import urljoin

LOG_TO_FILE = __debug__
if LOG_TO_FILE:
    logging.basicConfig(
        filename="gamesort.log", 
        level=logging.DEBUG, 
        format="%(asctime)s %(levelname)s %(message)s"
    )
else:
    logging.basicConfig(level=logging.CRITICAL)

# 클래스 밖 최상단에 위치
def needs_translation(text):
    import re
    return bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', text or ''))


class FetchWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, server_url, items, use_firestore_cache=True):
        super().__init__()
        self.server_url = server_url
        self.items = items
        self.use_firestore_cache = use_firestore_cache

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying request (attempt {retry_state.attempt_number}/3) after {retry_state.next_action.sleep} seconds"
        )
    )
    def get_dlsite_data(self, rj_code):
        url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja',
            'Referer': 'https://www.dlsite.com/maniax/',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
        cookies = {'adultconfirmed': '1'}

        try:
            logging.info(f"Fetching DLsite data for {rj_code}")
            response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
            response.encoding = 'utf-8'
            
            if response.status_code != 200:
                raise Exception(f"DLsite fetch failed: Status {response.status_code}")

            if 'age-verification' in response.url or 'adult_check' in response.text.lower():
                logging.warning(f"Adult verification page detected for {rj_code}")
                raise Exception("Adult verification required")

            soup = BeautifulSoup(response.text, 'html.parser')
            title_elem = soup.select_one('#work_name')
            if not title_elem:
                logging.error(f"No title found for RJ code {rj_code}")
                raise Exception("No title found")

            tags_elem = soup.select('div.main_genre a, div.work_genre a, .genre a')
            tags_jp = [tag.text.strip() for tag in tags_elem if tag.text.strip()]
            if not tags_jp:
                genre_th = soup.find('th', string=re.compile(r'ジャンル'))
                if genre_th:
                    genre_td = genre_th.find_next_sibling('td')
                    if genre_td:
                        tags_jp = [a.text.strip() for a in genre_td.select('a') if a.text.strip()]
            if not tags_jp:
                logging.warning(f"No genre tags found for {rj_code}")
                tags_jp = ["기타"]

            date_elem = soup.select_one('th:contains("販売日") + td a')
            thumb_elem = soup.select_one('meta[property="og:image"]') or soup.select_one('img.work_thumb')
            maker_elem = soup.select_one('span.maker_name a')

            thumbnail_url = ''
            if thumb_elem:
                thumbnail_url = thumb_elem.get('content') or thumb_elem.get('src')
                if thumbnail_url and not thumbnail_url.startswith('http'):
                    thumbnail_url = urljoin(url, thumbnail_url)

            data = {
                'rj_code': rj_code,
                'title_jp': title_elem.text.strip(),
                'tags_jp': tags_jp,
                'release_date': date_elem.text.strip() if date_elem else 'N/A',
                'thumbnail_url': thumbnail_url,
                'maker': maker_elem.text.strip() if maker_elem else 'N/A',
                'link': url,
                'platform': 'rj',
                'rating': 0.0,
                'timestamp': time.time()
            }
            logging.info(f"Fetched DLsite data for {rj_code}, tags_jp={tags_jp}")
            return data
        except Exception as e:
            logging.error(f"Error fetching DLsite data for {rj_code}: {e}", exc_info=True)
            return {'error': f'Game not found for {rj_code}', 'platform': 'rj', 'rj_code': rj_code}

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying server request (attempt {retry_state.attempt_number}/5) after {retry_state.next_action.sleep} seconds"
        )
    )
    def make_request(self, url, method='post', json_data=None):
        logging.debug(f"Sending {method.upper()} request to {url}")
        try:
            if method == 'post':
                response = requests.post(url, json=json_data, timeout=30)
            else:
                response = requests.get(url, timeout=10)
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
            logging.info(f"Starting fetch for {total_items} items")

            if self.use_firestore_cache:
                logging.info("Checking Firestore cache")
                response = self.make_request(f"{self.server_url}/games", method='post', json_data={"items": self.items})
                response_data = response.json()
                missing = response_data.get("missing", [])
                self.task_id = response_data.get("task_id")
                logging.info(f"Firestore cache check complete, missing items: {len(missing)}")
            else:
                logging.info("Firestore cache bypass mode enabled")
                missing = self.items
                response_data = {}

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

            if local_results:
                logging.info(f"Sending {len(local_results)} crawled items to server")
                self.make_request(f"{self.server_url}/games", method='post', json_data={"items": local_results})

            self.progress.emit(100)
            self.log.emit("데이터 가져오기 완료")

            # ✅ 최종 fetch 후 한 번만 emit
            logging.info("Re-fetching all items from cache after saving translated ones")
            final_response = self.make_request(
                f"{self.server_url}/games",
                method='post',
                json_data={"items": self.items}
            )
            final_data = final_response.json().get("results", [])
            self.result.emit(final_data)  # UI는 여기서만 갱신

            
            
            logging.info("Re-fetching all items from cache after saving translated ones")
            final_response = self.make_request(
                f"{self.server_url}/games",
                method='post',
                json_data={"items": self.items}
            )
            final_data = final_response.json().get("results", [])
            self.result.emit(final_data)  # 최종 UI 업데이트
        except Exception as e:
            self.error.emit(f"작업 실패: {str(e)}")
            logging.error(f"FetchWorker error: {str(e)}", exc_info=True)
        finally:
            self.finished.emit()

class MainWindowLogic(MainWindowUI):
    def __init__(self):
        super().__init__()
        self.results = []
        self.folder_path = None
        self.SERVER_URL = "https://gamesorter-28083845590.us-central1.run.app"
        self.worker = None

        self.select_folder_btn.clicked.connect(self.select_folder)
        self.fetch_data_btn.clicked.connect(self.fetch_game_data_and_update)
        self.rename_btn.clicked.connect(self.rename_files)
        self.remove_tag_btn.clicked.connect(self.remove_tags_from_selected)
        self.select_all_box.stateChanged.connect(self.toggle_all_selection)
        self.table.cellClicked.connect(self.on_table_cell_clicked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.log_label.setMaximumWidth(self.table.width())

    def update_suggested_name(self, row, tag):
        """태그 선택 시 suggested 이름을 즉시 업데이트"""
        try:
            if row >= len(self.results):
                logging.error(f"Invalid row index: {row}")
                return

            logging.debug(f"Updating suggested name for row {row} with tag {tag}")
            result = self.results[row]
            rj_code = result.get('rj_code') or "기타"
            game_data = result.get('game_data', {})
            
            title = game_data.get('title_kr') or game_data.get('title_jp') or result['original']
            title = re.sub(rf"[\[\(]?\b{rj_code}\b[\]\)]?", "", title, flags=re.IGNORECASE).strip()
            title = re.sub(rf"[ _\-]?\bRJ\s*{rj_code[2:]}\b", "", title, flags=re.IGNORECASE).strip()   
            title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')
            
            # ✅ 빈 문자열일 경우 대괄호 안 붙게 처리
            title = title.strip()
            if not title:
                result['suggested'] = f"[{rj_code}][{tag}]"
            else:
                result['suggested'] = f"[{rj_code}][{tag}] {title}"
            
            result['selected_tag'] = tag if tag else "기타"
            result['suggested'] = f"[{rj_code}][{result['selected_tag']}] {title}"
            
            self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))
            self.table.viewport().update()  # UI 즉시 갱신
            logging.debug(f"Updated suggested name for row {row}: {result['suggested']}")
        except Exception as e:
            logging.error(f"Update suggested name error: row={row}, tag={tag}, error={e}", exc_info=True)
            self.log_label.setText(f"태그 업데이트 오류: {str(e)}")

    def remove_tags_from_selected(self):
        """태그 제거: 모든 태그([RJ코드][태그])를 제거하고 순수 게임 이름만 남김"""
        try:
            updated_count = 0
            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                if not chk.isChecked():
                    continue

                result = self.results[row]
                game_data = result.get('game_data', {})
                # 제목 선택: title_kr > title_jp > original_title > original
                title = (
                    game_data.get('title_kr')
                    or game_data.get('title_jp')
                    or result.get('original_title')
                    or result['original']
                )
                rj_code = result.get('rj_code') or "기타"
                # RJ 코드와 특수문자 제거
                title = re.sub(rf"\b{rj_code}\b", "", title, flags=re.IGNORECASE).strip()
                title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')
                # 확장자 유지
                original_ext = os.path.splitext(result['original'])[1]
                updated_name = title if title.endswith(original_ext) else f"{title}{original_ext}"
                # 태그 제거된 이름 설정
                result['suggested'] = updated_name
                self.table.setItem(row, 2, QTableWidgetItem(updated_name))
                # QComboBox는 현재 상태 유지, selected_tag 초기화
                result['selected_tag'] = None
                updated_count += 1



            self.log_label.setText(f"선택된 항목 {updated_count}개에서 태그 제거 완료.")
            logging.info(f"Removed tags from {updated_count} items.")
        except Exception as e:
            logging.error(f"태그 제거 중 오류: {e}", exc_info=True)
            self.log_label.setText("태그 제거 처리 중 오류 발생")
            QMessageBox.critical(self, "오류", f"태그 제거 중 오류: {str(e)}")

    def fetch_game_data_and_update(self):
        if not self.results:
            self.log_label.setText("먼저 폴더를 선택하세요.")
            QMessageBox.warning(self, "경고", "폴더를 선택하세요.")
            return

        self.log_label.setText("Firestore에서 데이터 확인 중...")
        self.progress_bar.setValue(0)
        self.fetch_data_btn.setEnabled(False)

        items = [r.get('rj_code') or r['original'] for r in self.results]
        self.worker = FetchWorker(self.SERVER_URL, items, use_firestore_cache=True)
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

            logging.info("=== on_fetch_finished called ===")
            logging.info(f"Received game_data (length={len(game_data)}):")
            for i, d in enumerate(game_data):
                logging.info(f"[{i}] => {json.dumps(d, ensure_ascii=False)}")

            error_count = 0
            self.table.setUpdatesEnabled(False)

            for row, result in enumerate(self.results):
                match = None
                for d in game_data:
                    if result.get("rj_code") and d.get("rj_code") == result.get("rj_code"):
                        match = d
                        break
                    elif not result.get("rj_code") and d.get("title_kr") == result.get("original"):
                        match = d
                        break

                if not match or "error" in match:
                    rj_code = result.get('rj_code') or "기타"
                    result['suggested'] = f"[{rj_code}][기타] {result['original']}"
                    result['selected_tag'] = "기타"
                    error_count += 1
                    self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

                    combo = self.table.cellWidget(row, 3)
                    if not combo:
                        combo = QComboBox()
                        self.table.setCellWidget(row, 3, combo)
                    else:
                        try:
                            combo.currentTextChanged.disconnect()
                        except TypeError:
                            pass
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem("기타")
                    combo.setCurrentText("기타")
                    combo.blockSignals(False)
                    combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, text))
                    continue

                # 정상 데이터 처리
                result['game_data'] = match
                rj_code = result.get('rj_code') or match.get('rj_code') or "기타"

                tags = match.get('tags') or ["기타"]
                tags = [t for t in tags if t.strip()]  # ✅ 빈 문자열 제거
                tag = match.get('primary_tag') or (tags[0] if tags else "기타")
                if not tag or tag.strip() == "":
                    tag = "기타"

                # ✅ 제목 판단 + Fallback 처리
                original_title = result.get('original_title') or result.get('original')
                title_kr = match.get('title_kr') or match.get('title_jp') or original_title

                if not original_title or original_title.strip() == "" or len(original_title.strip()) < 2:
                    final_title = title_kr
                elif needs_translation(original_title):
                    final_title = title_kr
                else:
                    final_title = original_title

                if not final_title or final_title.strip() == "":
                    final_title = rj_code

                final_title = re.sub(rf"[\[\(]?\b{rj_code}\b[\]\)]?[)\s,;：]*", "", final_title, flags=re.IGNORECASE)
                final_title = re.sub(rf"[ _\-]?\bRJ\s*{rj_code[2:]}\b", "", final_title, flags=re.IGNORECASE).strip()
                final_title = re.sub(r'[?*:"<>|]', '', final_title).replace('/', '-')
                final_title = final_title.strip() if final_title else ""

                if not final_title:
                    result['suggested'] = f"[{rj_code}][{tag}]"
                else:
                    result['suggested'] = f"[{rj_code}][{tag}] {final_title}"


                result['selected_tag'] = tag
                self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

                combo = self.table.cellWidget(row, 3)
                if not combo:
                    combo = QComboBox()
                    self.table.setCellWidget(row, 3, combo)
                else:
                    try:
                        combo.currentTextChanged.disconnect()
                    except TypeError:
                        pass
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(tags)
                combo.setCurrentText(tag)
                combo.blockSignals(False)
                combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, text))

            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self.log_label.setText(f"게임명 변경 완료, {error_count}개 항목 실패")
            if error_count > 0:
                QMessageBox.warning(self, "경고", f"{error_count}개 항목을 처리하지 못했습니다. 로그를 확인하세요.")

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
            original_title = re.sub(rf"[Rr][Jj][_\-\s]?\d{{6,8}}", "", original, re.IGNORECASE).strip('_').strip()
            original_title = original_title if original_title and original_title != os.path.splitext(original)[1] else ''
            suggested = f"[{rj_code or '기타'}][기타] {original}"

            result = {
                'original': original,
                'original_title': original_title,
                'rj_code': rj_code,
                'suggested': suggested,
                'selected_tag': "기타",
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
            combo = QComboBox()
            combo.addItem("기타")
            combo.setCurrentText("기타")
            try:
                combo.currentTextChanged.disconnect()  # 기존 시그널 연결 해제
            except TypeError:
                pass
            combo.currentTextChanged.connect(lambda text, r=idx: self.update_suggested_name(r, text))  # ✅ row 고정
            self.table.setCellWidget(idx, 3, combo)

        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()  # UI 즉시 갱신
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
        self.fetch_data_btn.setEnabled(True)
        self.update_select_all_state()

    def on_checkbox_changed(self, row, checked):
        logging.debug(f"Checkbox changed: row={row}, checked={checked}")
        self.update_select_all_state()

    def on_table_cell_clicked(self, row, column):
        try:
            if column == 3:
                return
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
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
from urllib.parse import urljoin
from ui import MainWindowUI

# Logging 설정
LOG_TO_FILE = __debug__
if LOG_TO_FILE:
    logging.basicConfig(
        filename="gamesort.log",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s"
    )
else:
    logging.basicConfig(level=logging.CRITICAL)

# 유틸리티 함수
def needs_translation(text):
    return bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', text or ''))

def is_valid_game_file(name, folder_path=None):
    valid_exts = ['.zip', '.7z', '.rar', '.tar', '.gz']
    ext = os.path.splitext(name)[1].lower()
    if folder_path:
        full_path = os.path.join(folder_path, name)
        return os.path.isfile(full_path) and ext in valid_exts
    return ext in valid_exts

def clean_rj_code(title, rj_code):
    if not title or not rj_code:
        return title
    patterns = [
        rf"[\[\(]?\b{rj_code}\b[\]\)]?[)\s,;：]*",
        rf"[ _\-]?\bRJ\s*{rj_code[2:]}\b",
        rf"\b{rj_code}\b",
        rf"\bRJ\s*{rj_code[2:]}\b"
    ]
    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    logging.debug(f"Clean RJ code: {title} -> {cleaned}")
    return cleaned

# FetchWorker 클래스 (변경 없음)
class FetchWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, server_url, items, folder_path=None, use_firestore_cache=True):
        super().__init__()
        self.server_url = server_url
        self.items = items
        self.folder_path = folder_path
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

            original_title = title_elem.text.strip()
            cleaned_title = clean_rj_code(original_title, rj_code)

            data = {
                'rj_code': rj_code,
                'title_jp': cleaned_title,
                'original_title_jp': original_title,
                'tags_jp': tags_jp,
                'release_date': date_elem.text.strip() if date_elem else 'N/A',
                'thumbnail_url': thumbnail_url,
                'maker': maker_elem.text.strip() if maker_elem else 'N/A',
                'link': url,
                'platform': 'rj',
                'rating': 0.0,
                'timestamp': time.time()
            }
            logging.info(f"Fetched DLsite data for {rj_code}, title_jp={cleaned_title}, tags_jp={tags_jp}")
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
            return response.json()
        except Exception as e:
            logging.error(f"Request failed: {e}")
            raise
    
    def retry_fetch(self, request_items):
        retry_rj_codes = [
            item.get("rj_code") for item in request_items
            if item.get("platform") == "rj" and item.get("rj_code")
        ]

        if not retry_rj_codes:
            self.log.emit("재요청할 항목이 없습니다.")
            return

        self.log.emit("🌀 5초 후 캐시 재요청 중...")
        time.sleep(5)

        try:
            response_retry = self.make_request(
                f"{self.server_url}/games",
                method='post',
                json_data={"items": retry_rj_codes}
            )
            reloaded_results = response_retry.get("results", [])
            self.result.emit(reloaded_results)
            self.log.emit(f"✅ 재요청 완료: {len(reloaded_results)}개 항목")
        except Exception as e:
            logging.error(f"재요청 실패: {e}", exc_info=True)
            self.log.emit(f"재요청 실패: {str(e)}")

    def run(self):
        try:
            if self.folder_path:
                self.items = [item for item in self.items if is_valid_game_file(item, self.folder_path)]

            total_items = len(self.items)
            if total_items == 0:
                self.log.emit("처리할 압축 파일이 없습니다.")
                self.result.emit([])
                return

            self.log.emit(f"총 {total_items}개 파일 처리 시작")
            logging.info(f"Starting fetch for {total_items} items")

            request_items = []
            for item in self.items:
                rj_match = re.match(r'^[Rr][Jj]\d{6,8}$', item, re.IGNORECASE)
                if rj_match:
                    rj_code = rj_match.group(0).upper()
                    request_items.append({'rj_code': rj_code, 'platform': 'rj'})
                else:
                    rj_match = re.search(r"[Rr][Jj][_\-\s]?(\d{6,8})", item, re.IGNORECASE)
                    rj_code = ''
                    if rj_match:
                        full_match = rj_match.group(0)
                        rj_code = re.sub(r'[_\-\s]', '', full_match).upper()
                    request_items.append({
                        'rj_code': rj_code,
                        'platform': 'rj' if rj_code else 'steam',
                        'title': item
                    })
                logging.debug(f"Request item: {request_items[-1]}")

            response_data = []
            try:
                response = self.make_request(
                    f"{self.server_url}/games",
                    method='post',
                    json_data={"items": request_items}
                )
                response_data = response.get('results', [])
                logging.info(f"Initial server response: {len(response_data)} items")

                # 🔥🔥 여기!! missing 항목 강제 크롤링 🔥🔥
                missing = response.get("missing", [])
                logging.warning(f"[core] 서버 응답 missing 개수: {len(missing)}")
                for rj in missing:
                    self.log.emit(f"🔍 누락된 항목 크롤링 시도: {rj}")
                    try:
                        data = self.get_dlsite_data(rj)
                        # 🔁 서버에 다시 저장 요청
                        self.make_request(
                            f"{self.server_url}/games",
                            method='post',
                            json_data={"items": [data]}
                        )
                        logging.info(f"[core] 크롤링 및 저장 완료: {rj}")
                    except Exception as e:
                        logging.error(f"[core] 크롤링 실패: {rj} → {e}")

            except Exception as e:
                logging.error(f"Server request failed: {e}", exc_info=True)
                self.log.emit(f"서버 요청 실패, 로컬 크롤링으로 대체: {str(e)}")

            final_results = []
            for i, (item, req_item) in enumerate(zip(self.items, request_items)):
                rj_code = req_item.get('rj_code')
                match = None

                if response_data:
                    for d in response_data:
                        if rj_code and d.get('rj_code') == rj_code:
                            match = d
                            break
                        elif not rj_code and d.get('title_kr') == item:
                            match = d
                            break

                if match and match.get('platform') == 'rj' and 'error' not in match:
                    if match.get('title_kr'):
                        match['title_kr'] = clean_rj_code(match['title_kr'], rj_code)
                    if match.get('title_jp'):
                        match['title_jp'] = clean_rj_code(match['title_jp'], rj_code)
                    final_results.append(match)
                    logging.debug(f"Server match for {rj_code or item}: {match.get('title_kr')}")
                else:
                    if rj_code:
                        try:
                            data = self.get_dlsite_data(rj_code)
                            final_results.append(data)
                            logging.debug(f"Local crawl success for {rj_code}: {data.get('title_jp')}")
                            
                            # ✅ 크롤링 성공한 경우도 서버에 저장
                            self.make_request(
                                f"{self.server_url}/games",
                                method='post',
                                json_data={"items": [data]}
                            )
                        except Exception as e:
                            logging.error(f"Local crawl failed for {rj_code}: {e}")
                            
                            # ✅ fallback 데이터 생성
                            fallback = {
                                'rj_code': rj_code,
                                'platform': 'rj',
                                'title_kr': '',
                                'title_jp': '',
                                'tags': [],
                                'tags_jp': [],
                                'thumbnail_url': '',
                                'primary_tag': '기타',
                                'rating': 0.0,
                                'release_date': 'N/A',
                                'maker': '',
                                'link': '',
                                'timestamp': time.time()  # 🔥 핵심: 크롤링 시도한 증거
                            }

                            # ✅ 서버에 저장
                            self.make_request(
                                f"{self.server_url}/games",
                                method='post',
                                json_data={"items": [fallback]}
                            )

                            final_results.append(fallback)
                    else:
                        final_results.append({
                            'title': item,
                            'title_kr': item,
                            'primary_tag': '기타',
                            'tags': ['기타'],
                            'thumbnail_url': '',
                            'platform': 'steam',
                            'timestamp': time.time()
                        })

                self.progress.emit(int((i + 1) / total_items * 100))
                self.log.emit(f"처리 중: {item} ({i + 1}/{total_items})")

            logging.info(f"Returning {len(final_results)} results")
            self.result.emit(final_results)
            # ✅ 5초 후 재요청
            time.sleep(5)
            self.retry_fetch(request_items)
            self.log.emit(f"재로딩 완료")

        except Exception as e:
            self.error.emit(f"작업 실패: {str(e)}")
            logging.error(f"FetchWorker error: {str(e)}", exc_info=True)
        finally:
            self.finished.emit()

# MainWindowLogic 클래스
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
        try:
            if row >= len(self.results):
                logging.error(f"Invalid row index: {row}")
                return

            logging.debug(f"Updating suggested name for row {row} with tag {tag}")
            result = self.results[row]
            rj_code = result.get('rj_code') or "기타"
            game_data = result.get('game_data', {})

            title = game_data.get('title_kr') or game_data.get('title_jp') or result['original']
            title = clean_rj_code(title, rj_code)
            title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')

            title = title.strip()
            if not title:
                result['suggested'] = f"[{rj_code}][{tag}]"
            else:
                result['suggested'] = f"[{rj_code}][{tag}] {title}"

            result['selected_tag'] = tag if tag else "기타"
            self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))
            self.table.viewport().update()
            logging.debug(f"Updated suggested name for row {row}: {result['suggested']}")
        except Exception as e:
            logging.error(f"Update suggested name error: row={row}, tag={tag}, error={e}", exc_info=True)
            self.log_label.setText(f"태그 업데이트 오류: {str(e)}")

    def remove_tags_from_selected(self):
        try:
            updated_count = 0
            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                if not chk.isChecked():
                    continue

                result = self.results[row]
                game_data = result.get('game_data', {})
                title = (
                    game_data.get('title_kr')
                    or game_data.get('title_jp')
                    or result.get('original_title')
                    or result['original']
                )
                rj_code = result.get('rj_code') or "기타"
                title = clean_rj_code(title, rj_code)
                title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-')
                original_ext = os.path.splitext(result['original'])[1]
                updated_name = title if title.endswith(original_ext) else f"{title}{original_ext}"
                result['suggested'] = updated_name
                self.table.setItem(row, 2, QTableWidgetItem(updated_name))
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

        items = [r['original'] for r in self.results]
        self.worker = FetchWorker(self.SERVER_URL, items, self.folder_path, use_firestore_cache=True)
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

            logging.info(f"Received game_data (length={len(game_data)}):")
            for i, d in enumerate(game_data):
                logging.info(f"[{i}] => {json.dumps(d, ensure_ascii=False)}")

            error_count = 0
            self.table.setUpdatesEnabled(False)

            for row, result in enumerate(self.results):
                match = None
                rj_code = result.get('rj_code')
                for d in game_data:
                    if rj_code and d.get('rj_code') == rj_code:
                        match = d
                        break
                    elif not rj_code and d.get('title_kr') == result.get('original'):
                        match = d
                        break

                if not match or 'error' in match:
                    rj_code = rj_code or '기타'
                    result['suggested'] = f"[{rj_code}][기타] {result['original']}"
                    result['selected_tag'] = '기타'
                    error_count += 1
                    self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

                    combo = self.table.cellWidget(row, 3)
                    if not combo:
                        combo = QComboBox()
                        self.table.setCellWidget(row, 3, combo)
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem('기타')
                    combo.setCurrentText('기타')
                    combo.blockSignals(False)
                    combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, text))
                    logging.debug(f"No match for row {row}: rj_code={rj_code}, original={result['original']}")
                    continue

                result['game_data'] = match
                rj_code = rj_code or match.get('rj_code') or '기타'
                tags = match.get('tags') or ['기타']
                tags = [t for t in tags if t.strip()]
                tag = match.get('primary_tag') or (tags[0] if tags else '기타')
                if not tag or tag.strip() == '':
                    tag = '기타'

                original_title = result.get('original_title') or result.get('original')
                title_kr = match.get('title_kr') or match.get('title_jp') or original_title

                # ✅ 원래 이름에 일본어가 없다면 → 그걸 우선 사용
                if not needs_translation(original_title):
                    final_title = clean_rj_code(original_title, rj_code)
                else:
                    final_title = clean_rj_code(title_kr, rj_code)
                    if not final_title or final_title.strip() == '':
                        final_title = clean_rj_code(original_title, rj_code) or rj_code

                # ✅ 파일명에 사용 불가한 문자 제거
                final_title = re.sub(r'[?*:"<>|]', '', final_title).replace('/', '-').strip()

                result['suggested'] = f"[{rj_code}][{tag}] {final_title}" if final_title else f"[{rj_code}][{tag}]"
                result['selected_tag'] = tag
                self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

                combo = self.table.cellWidget(row, 3)
                if not combo:
                    combo = QComboBox()
                    self.table.setCellWidget(row, 3, combo)
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(tags)
                combo.setCurrentText(tag)
                combo.blockSignals(False)
                combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, text))
                logging.debug(f"Matched row {row}: rj_code={rj_code}, title_kr={title_kr}, final_title={final_title}")

            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self.log_label.setText(f"게임명 변경 완료, {error_count}개 항목 실패")
            if error_count > 0:
                QMessageBox.warning(self, "경고", f"{error_count}개 항목을 처리하지 못했습니다. 로그를 확인하세요.")

            self.status_label.setText(f"파일: {len(self.results)}개")
            self.update_select_all_state()

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
        try:
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
            files = [f for f in entries if is_valid_game_file(f, self.folder_path)]
            files.sort()

            if not files:
                self.log_label.setText("폴더에 파일이 없습니다.")
                self.status_label.setText("파일: 0개")
                self.fetch_data_btn.setEnabled(False)
                return

            self.table.setUpdatesEnabled(False)
            for idx, original in enumerate(files):
                rj_match = re.search(r"[Rr][Jj][_\-\s]?(\d{6,8})", original, re.IGNORECASE)
                rj_code = ''
                if rj_match:
                    full_match = rj_match.group(0)
                    rj_code = re.sub(r'[_\-\s]', '', full_match).upper()

                original_title = original
                if rj_code:
                    original_title = clean_rj_code(original, rj_code)
                    ext = os.path.splitext(original)[1]
                    if original_title.strip() == ext or not original_title.strip():
                        original_title = ''
                else:
                    name, ext = os.path.splitext(original)
                    original_title = name if name != ext else ''

                suggested = f"[{rj_code or '기타'}][기타] {original_title or original}"
                logging.debug(f"File: {original}, Extracted rj_code: '{rj_code}', Original title: '{original_title}'")

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
                combo.currentTextChanged.connect(lambda text, r=idx: self.update_suggested_name(r, text))
                self.table.setCellWidget(idx, 3, combo)

            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self.status_label.setText(f"파일: {len(self.results)}개")
            self.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
            self.fetch_data_btn.setEnabled(True)
            self.update_select_all_state()

        except Exception as e:
            logging.error(f"폴더 선택 오류: {e}", exc_info=True)
            self.log_label.setText(f"폴더 스캔 중 오류 발생: {str(e)}")
            QMessageBox.critical(self, "오류", f"폴더 스캔 중 오류: {str(e)}")

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
import os
import re
import json
import requests
import time
from bs4 import BeautifulSoup
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QCheckBox, QComboBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication
from dotenv import load_dotenv
import logging
import tenacity
from urllib.parse import urljoin
from ui import MainWindowUI
from PySide6.QtCore import QFile
import resources_rc

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
    
# .env 파일 로드
try:
    load_dotenv()
    logging.info(".env 파일 로드 성공")
except Exception as e:
    logging.warning(f".env 파일 로드 실패: {e}")

# 유틸리티 함수
def needs_translation(text):
    return bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', text or ''))

def is_valid_game_file(full_path):
    valid_exts = ['.zip', '.7z', '.rar', '.tar', '.gz']
    ext = os.path.splitext(full_path)[1].lower()
    return os.path.isfile(full_path) and ext in valid_exts

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

# FetchWorker 클래스
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

            tags_elem = soup.select('div.main_genre a')
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

            fallback = {
                'error': f'Game not found for {rj_code}',
                'rj_code': rj_code,
                'platform': 'rj',
                'title_jp': '',
                'tags': [],
                'tags_jp': [],
                'thumbnail_url': '',
                'primary_tag': '기타',
                'rating': 0.0,
                'release_date': 'N/A',
                'maker': '',
                'link': '',
                'status': '404',
                'permanent_error': True,
                'skip_translation': True,
                'timestamp': time.time()
            }
            return fallback

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=15),
        retry=tenacity.retry_if_exception_type(requests.exceptions.RequestException),
        before_sleep=lambda retry_state: logging.warning(
            f"Retrying server request (attempt {retry_state.attempt_number}/5) after {retry_state.next_action.sleep} seconds"
        )
    )
    def make_request(self, url, method='post', json_data=None, timeout=30):
        logging.debug(f"Sending {method.upper()} request to {url}")
        try:
            if method == 'post':
                response = requests.post(url, json=json_data, timeout=timeout)
            else:
                response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Request failed: {e}")
            raise
    
    def strip_local_fields(self, item):
        return {k: v for k, v in item.items() if not k.startswith("original_")}

    def handle_missing_items(self, missing):
        """missing 항목 처리를 위한 함수"""
        for rj in missing:
            self.log.emit(f"🔍 누락된 항목 크롤링 시도: {rj}")
            try:
                data = self.get_dlsite_data(rj)
                
                # 크롤링 성공한 경우에만 서버에 저장
                if 'error' not in data and data.get('title_jp'):
                    safe_data = self.strip_local_fields(data)
                    self.make_request(
                        f"{self.server_url}/games",
                        method='post',
                        json_data={"items": [safe_data]}
                    )
                    logging.info(f"[core] 크롤링 및 저장 완료: {rj}")
                else:
                    logging.warning(f"[core] 크롤링 실패 또는 데이터 불완전: {rj}, 서버에 저장하지 않음")
            except Exception as e:
                logging.error(f"[core] 크롤링 실패: {rj} → {e}")

    def create_fallback_data(self, rj_code, item):
        """fallback 데이터 생성을 위한 함수"""
        fallback = {
            'error': f'Game not found for {rj_code}',
            'rj_code': rj_code,
            'platform': 'rj',
            'title': item,
            'title_kr': '',
            'title_jp': '',
            'original_filename': clean_rj_code(item, rj_code),
            'tags': ["기타"],
            'tags_jp': [],
            'thumbnail_url': '',
            'primary_tag': '기타',
            'rating': 0.0,
            'release_date': 'N/A',
            'maker': '',
            'link': '',
            'status': '404',
            'permanent_error': True,
            'skip_translation': True,
            'timestamp': time.time()
        }
        return fallback

    def retry_fetch(self, request_items):
        try:
            logging.debug(f"🔄 retry_fetch 시작: {len(request_items)}개 항목")
            self.log.emit("🔄 재요청 준비 중...")
            
            retry_items = []
            for item in request_items:
                if (item.get("platform") == "rj" and 
                    item.get("rj_code") and 
                    not item.get("status") == "404" and 
                    not item.get("permanent_error")):
                    retry_items.append({
                        "rj_code": item.get("rj_code"),
                        "platform": "rj"
                    })
            
            logging.debug(f"🔍 재요청 목록 생성 완료: {len(retry_items)}개")

            if not retry_items:
                self.log.emit("재요청할 항목이 없습니다.")
                logging.debug("🚫 재요청 항목 없음, 함수 종료")
                return

            self.log.emit(f"🌀 재요청 준비: {len(retry_items)}개 항목")
            logging.debug("📡 서버에 재요청 시작...")
            
            try:
                response_retry = self.make_request(
                    f"{self.server_url}/games",
                    method='post',
                    json_data={"items": retry_items},
                    timeout=15
                )
                logging.debug("📥 서버 응답 수신 완료")
                reloaded_results = response_retry.get("results", [])
                self.result.emit(reloaded_results)
                self.log.emit(f"✅ 재요청 완료: {len(reloaded_results)}개 항목")
                logging.debug(f"✅ 재요청 처리 완료: {len(reloaded_results)}개 결과")
            except Exception as e:
                logging.error(f"재요청 실패: {e}", exc_info=True)
                self.log.emit(f"재요청 실패: {str(e)}")
        except Exception as e:
            logging.error(f"retry_fetch 전체 오류: {e}", exc_info=True)
            self.log.emit(f"재요청 처리 중 오류 발생: {str(e)}")
        finally:
            logging.debug("🏁 retry_fetch 함수 종료")

    def run(self):
        try:
            logging.debug(f"[run] 초기 self.items 개수: {len(self.items)}")
            for idx, item in enumerate(self.items):
                logging.debug(f"[run] 초기 item[{idx}]: {item}")

            if self.folder_path:
                logging.debug("[run] 유효성 검사 시작 (full_path 기준)")
                temp_items = []
                for idx, item in enumerate(self.items):
                    full_path = os.path.normpath(os.path.join(self.folder_path, item))
                    is_valid = is_valid_game_file(full_path)
                    logging.debug(f"   ↳ 검사 대상: {full_path} → is_valid={is_valid}")
                    if is_valid:
                        temp_items.append(item)

                self.items = temp_items
                logging.debug(f"[run] 필터링 후 self.items 개수: {len(self.items)}")
                for idx, item in enumerate(self.items):
                    logging.debug(f"[run] 남은 item[{idx}]: {item}")

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
                    request_items.append({'rj_code': rj_code, 'platform': 'rj', 'title': item})
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

                missing = response.get("missing", [])
                logging.warning(f"[core] 서버 응답 missing 개수: {len(missing)}")
                self.handle_missing_items(missing)  # 수정: handle_missing_items 호출

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
                            
                            if data.get('error'):
                                data = self.create_fallback_data(rj_code, item)  # 수정: create_fallback_data 호출
                                logging.debug(f"Enhanced fallback data with filename: {item}")
                            
                            final_results.append(data)
                            logging.debug(f"Process complete for {rj_code}: {data.get('title_jp') or data.get('title_kr')}")
                            
                            safe_data = self.strip_local_fields(data)
                            self.make_request(
                                f"{self.server_url}/games",
                                method='post',
                                json_data={"items": [safe_data]}
                            )
                        except Exception as e:
                            logging.error(f"Local crawl failed for {rj_code}: {e}")
                            
                            data = self.create_fallback_data(rj_code, item)  # 수정: create_fallback_data 호출
                            try:
                                safe_data = self.strip_local_fields(data)
                                self.make_request(
                                    f"{self.server_url}/games",
                                    method='post',
                                    json_data={"items": [safe_data]}
                                )
                                logging.info(f"Fallback data saved for {rj_code}")
                            except Exception as save_error:
                                logging.error(f"Failed to save fallback data: {save_error}")

                            final_results.append(data)
                    else:
                        final_results.append({
                            'title': item,
                            'title_kr': item,
                            'original_title': item,
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
            
            logging.debug("🕒 5초 대기 시작...")
            self.log.emit("🕒 5초 대기 중...")
            time.sleep(5)
            logging.debug("⏰ 5초 대기 완료, 재요청 시작...")
            
            self.retry_fetch(request_items)
            logging.debug("✅ retry_fetch 완료")
            self.log.emit(f"재로딩 완료")

        except Exception as e:
            logging.error(f"FetchWorker error: {str(e)}", exc_info=True)
            self.error.emit(f"작업 실패: {str(e)}")
        finally:
            logging.debug("🏁 run 메서드 종료")
            self.finished.emit()

# MainWindowLogic 클래스
class MainWindowLogic(MainWindowUI):
    def __init__(self):
        super().__init__()
        
        self.results = []
        self.folder_path = None
        
        self.SERVER_URL = os.getenv("GAMESORTER_API_URL", "https://gamesorter-28083845590.us-central1.run.app")
        logging.info(f"서버 URL 설정: {self.SERVER_URL}")
            
        self.worker = None

        self.select_folder_btn.clicked.connect(self.select_folder)
        self.fetch_data_btn.clicked.connect(self.fetch_game_data_and_update)
        self.rename_btn.clicked.connect(self.rename_files)
        self.remove_tag_btn.clicked.connect(self.remove_tags_from_selected)
        self.select_all_box.stateChanged.connect(self.toggle_all_selection)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        
        file = QFile(":/dark_style.qss")
        if file.open(QFile.ReadOnly | QFile.Text):
            self.setStyleSheet(file.readAll().data().decode())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.log_label.setMaximumWidth(self.table.width())

    def update_suggested_name(self, row, tag=None, title_source=None):
        try:
            logging.warning(f"🔥 [START] update_suggested_name() 진입: row={row}, tag={tag}, title_source={title_source}")

            if row >= len(self.results):
                logging.error(f"❌ Invalid row index: {row} (총 rows: {len(self.results)})")
                return

            result = self.results[row]
            rj_code = result.get('rj_code') or "기타"
            game_data = result.get('game_data', {})

            logging.debug(f"📦 result={result}")
            logging.debug(f"📦 game_data={game_data}")

            # 제목 소스 결정
            title_kr = game_data.get('title_kr', '').strip()
            title_jp = game_data.get('title_jp', '').strip()
            original_title = result.get('original_title', '').strip()
            original = result.get('original', '').strip()
            original_filename = game_data.get('original_filename', '').strip()  # 추가: original_filename 지원

            logging.debug(f"🔍 제목 후보들: title_kr='{title_kr}', title_jp='{title_jp}', original_title='{original_title}', original='{original}', original_filename='{original_filename}'")

            # 드롭다운에서 선택된 제목 소스 사용, 없으면 기존 우선순위
            if title_source:
                selected_source = title_source
            else:
                # 기존 우선순위: original_title(일본어 아님) > title_kr > title_jp > original_filename > original > rj_code
                if original_title and not needs_translation(original_title):
                    selected_source = "기존 이름"
                elif title_kr:
                    selected_source = "한국어 이름"
                elif title_jp:
                    selected_source = "일본어 이름"
                else:
                    selected_source = "기존 이름"

            # results에 선택된 소스 저장
            result['selected_title_source'] = selected_source

            # 제목 선택
            if selected_source == "기존 이름":
                title = original_title or original_filename or original or rj_code
            elif selected_source == "한국어 이름":
                title = title_kr or title_jp or original_title or original_filename or original or rj_code
            else:  # 일본어 이름
                title = title_jp or title_kr or original_title or original_filename or original or rj_code

            # 태그가 제공되지 않으면 기존 태그 사용
            if tag is None:
                tag = result.get('selected_tag', '기타')

            # RJ 코드 제거
            title = clean_rj_code(title, rj_code)
            logging.debug(f"🧪 RJ 제거 후 title: '{title}'")

            # 특수문자 제거
            title = re.sub(r'[?*:"<>|]', '', title).replace('/', '-').strip()
            logging.debug(f"🧪 특수문자 제거 후 title: '{title}'")

            # 확장자 가져오기
            original_ext = os.path.splitext(original)[1]
            logging.debug(f"📎 확장자: '{original_ext}'")

            # 제목이 완전히 비어있다면
            if not title:
                result['suggested'] = f"[{rj_code}][{tag}]{original_ext}"
                logging.debug(f"📝 제목 없음 → '{result['suggested']}'")
            else:
                if title.lower().endswith(original_ext.lower()):
                    result['suggested'] = f"[{rj_code}][{tag}] {title}"
                else:
                    result['suggested'] = f"[{rj_code}][{tag}] {title}{original_ext}"
                logging.debug(f"✅ 최종 파일명: '{result['suggested']}'")

            result['selected_tag'] = tag if tag else "기타"
            self.table.setItem(row, 2, QTableWidgetItem(result['suggested']))

            # 제목 소스 콤보박스 업데이트
            combo = self.table.cellWidget(row, 4)
            if combo:
                combo.blockSignals(True)
                combo.setCurrentText(selected_source)
                combo.blockSignals(False)

            self.table.viewport().update()

            logging.warning(f"✅ [END] update_suggested_name 완료: {result['suggested']}")

        except Exception as e:
            logging.error(f"💥 update_suggested_name 실패: row={row}, tag={tag}, title_source={title_source}, error={e}", exc_info=True)
            self.log_label.setText(f"제목 업데이트 오류: {str(e)}")

    def remove_tags_from_selected(self):
        try:
            updated_count = 0
            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                if not chk.isChecked():
                    continue

                result = self.results[row]
                game_data = result.get('game_data', {})
                selected_source = result.get('selected_title_source', '기존 이름')
                
                title_kr = game_data.get('title_kr', '').strip()
                title_jp = game_data.get('title_jp', '').strip()
                original_title = result.get('original_title', '').strip()
                original = result.get('original', '').strip()
                original_filename = game_data.get('original_filename', '').strip()
                rj_code = result.get('rj_code') or "기타"

                if selected_source == "기존 이름":
                    title = original_title or original_filename or original or rj_code
                elif selected_source == "한국어 이름":
                    title = title_kr or title_jp or original_title or original_filename or original or rj_code
                else:
                    title = title_jp or title_kr or original_title or original_filename or original or rj_code

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

        logging.debug(f"🔍 self.results 총 {len(self.results)}개:")
        for idx, result in enumerate(self.results):
            logging.debug(f"  🔸 ROW {idx}: RJ={result.get('rj_code')}, title={result.get('original')}")

        items = []
        for idx, r in enumerate(self.results):
            rj_code = r.get('rj_code', '').strip()
            title = r.get('original', '').strip()

            if not title:
                logging.warning(f"❌ [ROW {idx}] title 없음 → 제외")
                continue

            item = r.get("relative_path")
            if not item:
                logging.warning(f"❌ [ROW {idx}] relative_path 없음 → 제외")
                continue
            items.append(item)
            logging.debug(f"✅ [ROW {idx}] 요청 포함: {item}")

        logging.debug(f"🚀 서버로 보낼 items 개수: {len(items)}")
        for i, it in enumerate(items):
            logging.debug(f"  📨 ITEM[{i}]: {it}")

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
                    result['selected_tag'] = '기타'
                    result['selected_title_source'] = '기존 이름'
                    self.update_suggested_name(row, '기타')

                    # 태그 선택 콤보박스
                    tag_combo = self.table.cellWidget(row, 3)
                    if not tag_combo:
                        tag_combo = QComboBox()
                        self.table.setCellWidget(row, 3, tag_combo)
                    tag_combo.blockSignals(True)
                    tag_combo.clear()
                    tag_combo.addItem('기타')
                    tag_combo.setCurrentText('기타')
                    tag_combo.blockSignals(False)
                    tag_combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, tag=text))

                    # 제목 소스 콤보박스
                    source_combo = self.table.cellWidget(row, 4)
                    if not source_combo:
                        source_combo = QComboBox()
                        self.table.setCellWidget(row, 4, source_combo)
                    source_combo.blockSignals(True)
                    source_combo.clear()
                    source_combo.addItems(["기존 이름", "한국어 이름", "일본어 이름"])
                    source_combo.setCurrentText('기존 이름')
                    source_combo.blockSignals(False)
                    source_combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, title_source=text))
                    
                    logging.debug(f"No match for row {row}: rj_code={rj_code}, original={result['original']}")
                    error_count += 1
                    continue

                result['game_data'] = match
                rj_code = rj_code or match.get('rj_code') or '기타'
                tags = match.get('tags') or ['기타']
                tags = [t for t in tags if t.strip()]
                tag = match.get('primary_tag') or (tags[0] if tags else '기타')
                if not tag or tag.strip() == '':
                    tag = '기타'

                result['selected_tag'] = tag

                # 기본 제목 소스 결정
                title_kr = match.get('title_kr', '').strip()
                title_jp = match.get('title_jp', '').strip()
                original_title = result.get('original_title', '').strip()
                original_filename = match.get('original_filename', '').strip()
                if original_title and not needs_translation(original_title):
                    result['selected_title_source'] = '기존 이름'
                elif title_kr:
                    result['selected_title_source'] = '한국어 이름'
                elif title_jp:
                    result['selected_title_source'] = '일본어 이름'
                else:
                    result['selected_title_source'] = '기존 이름'

                self.update_suggested_name(row, tag)

                # 태그 선택 콤보박스
                tag_combo = self.table.cellWidget(row, 3)
                if not tag_combo:
                    tag_combo = QComboBox()
                    self.table.setCellWidget(row, 3, tag_combo)
                tag_combo.blockSignals(True)
                tag_combo.clear()
                tag_combo.addItems(tags)
                tag_combo.setCurrentText(tag)
                tag_combo.blockSignals(False)
                tag_combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, tag=text))

                # 제목 소스 콤보박스
                source_combo = self.table.cellWidget(row, 4)
                if not source_combo:
                    source_combo = QComboBox()
                    self.table.setCellWidget(row, 4, source_combo)
                source_combo.blockSignals(True)
                source_combo.clear()
                source_combo.addItems(["기존 이름", "한국어 이름", "일본어 이름"])
                source_combo.setCurrentText(result['selected_title_source'])
                source_combo.blockSignals(False)
                source_combo.currentTextChanged.connect(lambda text, r=row: self.update_suggested_name(r, title_source=text))

                logging.debug(f"Matched row {row}: rj_code={rj_code}, tag={tag}, title_source={result['selected_title_source']}")

            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self.log_label.setText(f"게임명 변경 완료, {error_count}개 항목 실패")
            if error_count > 0:
                failed_items = []
                for row, result in enumerate(self.results):
                    gd = result.get("game_data")
                    if (
                        not gd
                        or 'error' in gd
                        or not gd.get('title_kr') and not gd.get('title_jp')
                    ):
                        filename = result.get('original', f'row={row}')
                        failed_items.append(f"[{row}] {filename}")

                logging.warning(f"⚠️ 처리 실패한 항목 {error_count}개:")
                for item in failed_items:
                    logging.warning(f"  ❌ {item}")

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

            files = []
            for dirpath, _, filenames in os.walk(self.folder_path):
                for f in filenames:
                    full_path = os.path.join(dirpath, f)
                    if is_valid_game_file(full_path):
                        full_path = os.path.join(dirpath, f)
                        rel_path = os.path.relpath(full_path, self.folder_path)
                        files.append((rel_path, full_path))
            files.sort(key=lambda x: x[0])

            if not files:
                self.log_label.setText("폴더에 파일이 없습니다.")
                self.status_label.setText("파일: 0개")
                self.fetch_data_btn.setEnabled(False)
                return

            self.table.setUpdatesEnabled(False)

            for idx, (rel_path, full_path) in enumerate(files):
                original = os.path.basename(rel_path)
                ext = os.path.splitext(original)[1]

                rj_match = re.search(r"[Rr][Jj][_\-\s]?(\d{6,8})", original, re.IGNORECASE)
                rj_code = ''
                if rj_match:
                    full_match = rj_match.group(0)
                    rj_code = re.sub(r'[_\-\s]', '', full_match).upper()

                original_title = os.path.splitext(original)[0]
                if rj_code:
                    original_title = clean_rj_code(original_title, rj_code)
                    if not original_title.strip():
                        original_title = ''
                else:
                    if original_title.strip() == ext or not original_title.strip():
                        original_title = ''

                final_title = original_title or os.path.splitext(original)[0]
                if not final_title.lower().endswith(ext.lower()):
                    final_title += ext

                suggested = f"[{rj_code or '기타'}][기타] {final_title}"

                logging.debug(f"File: {rel_path}, RJ: '{rj_code}', Title: '{original_title}'")

                result = {
                    'original': original,
                    'original_title': original_title,
                    'rj_code': rj_code,
                    'suggested': suggested,
                    'selected_tag': "기타",
                    'selected_title_source': "기존 이름",
                    'path': full_path,
                    'game_data': {},
                    'relative_path': rel_path
                }
                self.results.append(result)

                chk = QCheckBox()
                chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
                self.table.insertRow(idx)
                self.table.setCellWidget(idx, 0, chk)
                self.table.setItem(idx, 1, QTableWidgetItem(original))
                self.table.setItem(idx, 2, QTableWidgetItem(suggested))

                # 태그 선택 콤보박스
                tag_combo = QComboBox()
                tag_combo.addItem("기타")
                tag_combo.setCurrentText("기타")
                tag_combo.currentTextChanged.connect(lambda text, r=idx: self.update_suggested_name(r, tag=text))
                self.table.setCellWidget(idx, 3, tag_combo)

                # 제목 소스 콤보박스
                source_combo = QComboBox()
                source_combo.addItems(["기존 이름", "한국어 이름", "일본어 이름"])
                source_combo.setCurrentText("기존 이름")
                source_combo.currentTextChanged.connect(lambda text, r=idx: self.update_suggested_name(r, title_source=text))
                self.table.setCellWidget(idx, 4, source_combo)

            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self.status_label.setText(f"파일: {len(self.results)}개")
            self.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
            self.fetch_data_btn.setEnabled(True)
            self.update_select_all_state()
            
            for idx, result in enumerate(self.results):
                logging.debug(f"[📋 RESULT CHECK] row={idx}, RJ={result.get('rj_code')}, title={result.get('original')}")

        except Exception as e:
            logging.error(f"폴더 선택 오류: {e}", exc_info=True)
            self.log_label.setText(f"폴더 스캔 중 오류 발생: {str(e)}")
            QMessageBox.critical(self, "오류", f"폴더 스캔 중 오류: {str(e)}")

    def on_checkbox_changed(self, row, checked):
        logging.debug(f"Checkbox changed: row={row}, checked={checked}")
        self.update_select_all_state()

    def on_table_cell_clicked(self, row, column):
        try:
            if column in (3, 4):  # 태그 선택 또는 제목 소스 열 클릭 시 무시
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
            logging.debug("🔁 update_select_all_state 호출됨")
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
                logging.debug("   ✅ 전체 체크됨 → select_all_box.setChecked(True)")
                self.select_all_box.setChecked(True)
            elif none_checked:
                logging.debug("   ❎ 전체 해제됨 → select_all_box.setChecked(False)")
                self.select_all_box.setChecked(False)
            else:
                logging.debug("   ⚠️ 일부만 선택됨 → select_all_box.setTristate()")
                self.select_all_box.setTristate(True)
                self.select_all_box.setCheckState(Qt.PartiallyChecked)
            self.select_all_box.blockSignals(False)
        except Exception as e:
            logging.error(f"Update select all state error: {e}", exc_info=True)

    def toggle_all_selection(self, state):
        try:
            logging.debug(f"🟩 toggle_all_selection 호출됨: state={state}")

            any_unchecked = any(
                not self.table.cellWidget(row, 0).isChecked()
                for row in range(self.table.rowCount())
            )
            checked = any_unchecked

            logging.debug(f"   → 전체를 {'선택' if checked else '해제'}합니다.")

            self.table.setUpdatesEnabled(False)

            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                chk.blockSignals(True)
                logging.debug(f"   🔄 row {row} 이전 체크 상태: {chk.isChecked()}")
                chk.setChecked(checked)
                chk.blockSignals(False)

            self.table.setUpdatesEnabled(True)

            self.update_select_all_state()

            self.log_label.setText(f"전체 선택 {'완료' if checked else '해제'}")
            logging.debug(f"✅ 전체 {'선택' if checked else '해제'} 완료")

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

                original_ext = os.path.splitext(original_name)[1]
                if not new_name.lower().endswith(original_ext.lower()):
                    new_name += original_ext
                
                if new_name == original_name or '[오류]' in new_name:
                    continue

                rel_dir = os.path.dirname(self.results[row]['relative_path'])
                target_dir = os.path.join(self.folder_path, rel_dir) if rel_dir else self.folder_path
                os.makedirs(target_dir, exist_ok=True)

                new_path = os.path.join(target_dir, new_name)
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
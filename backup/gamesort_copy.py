import sys
import os
import shutil
import json
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QCheckBox, QHBoxLayout, QLabel, QHeaderView,
    QMessageBox, QProgressBar, QLineEdit
)
from PySide6.QtCore import Qt, QThread, Signal
from openai import OpenAI
import time
import concurrent.futures
from queue import Queue
import logging

# 로깅 설정
logging.basicConfig(filename="gamesort.log", level=logging.INFO, format="%(asctime)s %(message)s")

class GPTWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, client, files, enhanced_files, batch_size=10):
        super().__init__()
        self.client = client
        self.files = files
        self.enhanced_files = enhanced_files
        self.batch_size = batch_size

    def run(self):
        try:
            total_files = len(self.files)
            result_queue = Queue()
            batches = [self.files[i:i + self.batch_size] for i in range(0, total_files, self.batch_size)]
            enhanced_batches = [self.enhanced_files[i:i + self.batch_size] for i in range(0, total_files, self.batch_size)]
            total_batches = len(batches)
            self.log.emit(f"총 {total_batches}개 배치로 처리 시작")

            def process_batch(batch_idx, batch_files, batch_enhanced):
                try:
                    file_prompts = []
                    for i, (original, enhanced) in enumerate(zip(batch_files, batch_enhanced)):
                        file_prompts.append(f"{i+1}. 원본파일명: {original}, DLsite정보: {enhanced}")

                    prompt_text = (
                        "다음은 일본 게임 압축파일의 이름 목록입니다.\n"
                        "각 이름을 기반으로 아래 규칙에 따라 새 이름을 제안해 주세요:\n"
                        "1. 모든 태그는 대괄호 [ ] 안에 표기합니다.\n"
                        "2. 첫 번째 태그는 파일명 또는 제목에 포함된 정보에 따라 다음 중 하나를 선택합니다:\n"
                        "   - 'RJ'로 시작하는 6~8자리 숫자가 있을 경우: [RJ123456]처럼 정확히 표기합니다.\n"
                        "   - '렌파이', '쯔꾸르' 등 툴 정보가 있는 경우: 각각 [렌파이], [쯔꾸르]로 표기합니다.\n"
                        "   - 그 외 분류 정보가 없을 경우: [기타]로 표기합니다.\n"
                        "⚠️ 절대 [RJ없음], [RJ코드], [분류없음] 같은 태그를 사용하지 마세요. 이런 태그는 규칙 위반입니다. 무조건 [기타]로 통일하세요.\n"
                        "3. 두 번째 태그는 장르 키워드를 넣습니다:\n"
                        "   - [청아], [순애], [NTR], [RPG] 등 장르적 키워드가 제목이나 설명에 명확히 드러나는 경우 사용합니다.\n"
                        "   - 빼앗는다, 유혹한다 같은 표현은 NTR로 간주하지 마세요.\n"
                        "   - 장르를 판단하기 어려운 경우 [기타]로 표기합니다.\n"
                        "4. 제목 정리 규칙:\n"
                        "   - 파일명에 이미 한국어 제목이 포함된 경우, 해당 한국어 부분을 우선 사용하세요.\n"
                        "   - 일본어 제목만 있는 경우, 반드시 번역해서 한국어 제목으로 변환하세요.\n"
                        "     번역이 어려운 부분이 있더라도 가능한 부분만이라도 부분 번역해 주세요.\n"
                        "     예: オ○○の冒険生活 → 오○○의 모험 생활\n"
                        "     예: ☆特別なApp☆ → ☆특별한 App☆\n"
                        "   - 고유명사(작품명, 캐릭터명 등)는 번역하지 않고 그대로 유지하세요.\n"
                        "   - 제목은 자연스럽게 다듬지 마세요. 직역 중심으로, 원문의 의미를 그대로 살려서 번역하세요.\n"
                        "   - 의미가 불명확하거나 검열된 문장이 포함된 경우에도 가능한 번역을 시도한 뒤, 남은 부분은 원문 그대로 둡니다.\n"
                        "5. 출력 형식은 다음과 같습니다:\n"
                        "[분류][태그]정리된제목.기존파일확장자\n"
                        "6. 제목마다 한 줄씩, 번호 없이, 오직 결과만 출력해 주세요.\n"
                        "7. 출력에는 예시나 부가설명 없이, 곧바로 첫 번째 결과부터 나열해 주세요.\n"
                        "8. 파일 이름에는 사용할 수 없는 특수문자 (예: ?, *, :, <, >, /, \\, |, 큰따옴표 등)를 절대 포함하지 마세요.\n"
                        "   특히 물음표(?)는 쉼표(,)로 대체해 주세요.\n"
                        "입력:\n" + "\n".join(file_prompts)
                    )


                    self.log.emit(f"배치 {batch_idx + 1}/{total_batches} 처리 중...")
                    logging.info(f"Processing batch {batch_idx + 1}/{total_batches}")

                    # API 호출 (재시도 로직 포함)
                    for attempt in range(3):
                        try:
                            response = self.client.chat.completions.create(
                                model="gpt-4o",
                                messages=[
                                    {"role": "system", "content": "당신은 압축 게임 파일 이름을 정리하는 전문가입니다."},
                                    {"role": "user", "content": prompt_text}
                                ],
                                temperature=0.2
                            )
                            answer = response.choices[0].message.content.strip().splitlines()
                            return batch_idx, answer
                        except Exception as e:
                            if "429" in str(e):  # Rate limit
                                self.log.emit(f"배치 {batch_idx + 1} 재시도 {attempt + 1}/3...")
                                time.sleep(2 ** attempt)
                            else:
                                raise
                    raise Exception("API 호출 실패")
                except Exception as e:
                    self.log.emit(f"배치 {batch_idx + 1} 오류: {str(e)}")
                    logging.error(f"Batch {batch_idx + 1} error: {str(e)}")
                    return batch_idx, [f"[오류][기타]{f}" for f in batch_files]

            start_time = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(process_batch, i, batch_files, batch_enhanced)
                    for i, (batch_files, batch_enhanced) in enumerate(zip(batches, enhanced_batches))
                ]
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    batch_idx, batch_result = future.result()
                    result_queue.put((batch_idx, batch_result))
                    self.progress.emit(int((i + 1) / total_batches * 50))
                    QApplication.processEvents()

            # 결과 정렬
            final_results = []
            while not result_queue.empty():
                batch_idx, batch_result = result_queue.get()
                final_results.append((batch_idx, batch_result))

            final_results.sort()  # 배치 순서 보장
            answer = []
            for _, batch_result in final_results:
                answer.extend(batch_result)

            self.result.emit(answer)
            self.progress.emit(100)
            self.log.emit("GPT 분석 완료")
            logging.info(f"AI 분석 완료: {len(answer)}개 파일, 소요 시간: {time.time() - start_time:.2f}초")
        except Exception as e:
            self.error.emit(str(e))
            logging.error(f"GPTWorker error: {str(e)}")
        finally:
            self.finished.emit()

class TagWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, client, results, batch_size=10):
        super().__init__()
        self.client = client
        self.results = results
        self.batch_size = batch_size

    def run(self):
        try:
            total = len(self.results)
            updated_results = self.results.copy()
            update_queue = Queue()
            batches = [self.results[i:i + self.batch_size] for i in range(0, total, self.batch_size)]
            total_batches = len(batches)
            self.log.emit(f"총 {total_batches}개 배치로 태그 보완 시작")

            def process_batch(batch_idx, batch_results):
                try:
                    prompt_parts = []
                    indices = []
                    for i, result in enumerate(batch_results):
                        suggested = result['suggested']
                        match = re.match(r"\[(.*?)\]\[(.*?)\](.+)", suggested)
                        if not match:
                            continue
                        engine, tag, title = match.groups()
                        need_engine = engine.strip() in ["", "?", "기타"]
                        need_tag = tag.strip() in ["", "기타"]
                        if not need_engine and not need_tag:
                            continue
                        rj_match = re.search(r"RJ\d{6,8}", result['original'], re.IGNORECASE)
                        if rj_match:
                            rj_code = rj_match.group(0)
                            data = self.get_dlsite_data(rj_code)
                            if data:
                                new_engine = data['engine'] if need_engine else engine
                                new_tag = data['tag'] if need_tag else tag
                                new_name = f"[{new_engine}][{new_tag}]{title}"
                                if new_name != suggested:
                                    return batch_idx, [(i, new_name)]
                        prompt_parts.append(f"{i+1}. 제목: {title}, 엔진: {engine}, 태그: {tag}")
                        indices.append(i)

                    if not prompt_parts:
                        return batch_idx, []

                    instructions = [
                        "각 제목에 대해 다음을 수행:",
                        "- 엔진이 [기타]면 [렌파이], [쯔꾸르], [RJ코드] 중 적절한 값 추천, 모르면 [기타].",
                        "- 태그가 [기타]면 장르 키워드(예: NTR, RPG) 추천, 모르면 [기타].",
                        "형식: [엔진][태그] (번호 없이, 각 제목별 한 줄)."
                    ]
                    prompt = "\n".join(prompt_parts) + "\n\n" + "\n".join(instructions)

                    self.log.emit(f"배치 {batch_idx + 1}/{total_batches} 태그 보완 중...")
                    logging.info(f"Processing tag batch {batch_idx + 1}/{total_batches}")

                    # API 호출 (재시도 로직 포함)
                    for attempt in range(3):
                        try:
                            response = self.client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[
                                    {"role": "system", "content": "일본 게임 분석기입니다."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.3
                            )
                            replies = response.choices[0].message.content.strip().splitlines()
                            updates = []
                            for idx, reply in zip(indices, replies):
                                match = re.match(r"\[(.*?)\]\[(.*?)\]", reply)
                                if match:
                                    new_engine, new_tag = match.groups()
                                    title = batch_results[idx]['suggested'].split(']', 2)[-1]
                                    new_name = f"[{new_engine}][{new_tag}]{title}"
                                    if new_name != batch_results[idx]['suggested']:
                                        updates.append((idx, new_name))
                            return batch_idx, updates
                        except Exception as e:
                            if "429" in str(e):
                                self.log.emit(f"배치 {batch_idx + 1} 재시도 {attempt + 1}/3...")
                                time.sleep(2 ** attempt)
                            else:
                                raise
                    raise Exception("API 호출 실패")
                except Exception as e:
                    self.log.emit(f"배치 {batch_idx + 1} 오류: {str(e)}")
                    logging.error(f"Tag batch {batch_idx + 1} error: {str(e)}")
                    return batch_idx, []

            start_time = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(process_batch, i, batch)
                    for i, batch in enumerate(batches)
                ]
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    batch_idx, updates = future.result()
                    for local_idx, new_name in updates:
                        global_idx = batch_idx * self.batch_size + local_idx
                        update_queue.put((global_idx, new_name))
                    self.progress.emit(int((i + 1) / total_batches * 100))
                    QApplication.processEvents()

            while not update_queue.empty():
                idx, new_name = update_queue.get()
                updated_results[idx]['suggested'] = new_name

            self.result.emit(updated_results)
            self.log.emit("GPT 태그 보완 완료")
            logging.info(f"태그 보완 완료: 소요 시간: {time.time() - start_time:.2f}초")
        except Exception as e:
            self.error.emit(str(e))
            logging.error(f"TagWorker error: {str(e)}")
        finally:
            self.finished.emit()

    def get_dlsite_data(self, rj_code):
        cache_file = "dlsite_cache.json"
        cache = self.load_cache()
        if rj_code in cache:
            return cache[rj_code]

        try:
            url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('h1', id='work_name')
            if not title_tag:
                return None

            title = title_tag.text.strip()
            tags = [tag.text.strip() for tag in soup.find_all('span', class_='gtag') if tag.text.strip()]
            maker = soup.find('span', class_='maker_name')
            maker = maker.text.strip() if maker else ""
            release_date = soup.find('th', string='販売日')
            release_date = release_date.find_next('td').text.strip() if release_date else ""

            engine = rj_code
            if any("RPG" in tag or "쯔꾸르" in tag for tag in tags):
                engine = "쯔꾸르"
            elif any("렌파이" in tag or "Ren'Py" in tag for tag in tags):
                engine = "렌파이"

            data = {
                "title": title,
                "engine": engine,
                "tag": tags[0] if tags else "",
                "maker": maker,
                "release_date": release_date
            }
            cache[rj_code] = data
            self.save_cache(cache_file, cache)
            time.sleep(1)
            return data
        except Exception:
            return None

    def load_cache(self):
        try:
            if os.path.exists("dlsite_cache.json"):
                with open("dlsite_cache.json", 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except:
            return {}

    def save_cache(self, cache_file, cache):
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except:
            pass

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("게임 압축파일 정리기 - AI 모드")
        self.setGeometry(100, 100, 800, 600)
        self.results = []
        self.cache_file = "dlsite_cache.json"
        self.cache = self.load_cache()
        self.client = None

        main_widget = QWidget()
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.select_btn = QPushButton("\U0001F4C1 폴더 선택")
        self.analyze_btn = QPushButton("\U0001F9E0 AI 분석 실행")
        self.gpt_tag_btn = QPushButton("\U0001F50D 빈 태그 보완")
        self.dlsite_btn = QPushButton("\U0001F310 DLsite 검색")
        top_layout.addWidget(self.select_btn)
        top_layout.addWidget(self.analyze_btn)
        top_layout.addWidget(self.gpt_tag_btn)
        top_layout.addWidget(self.dlsite_btn)

        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("OpenAI API 키 입력")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_toggle = QPushButton("👁️")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.setFixedWidth(30)
        self.api_key_toggle.clicked.connect(self.toggle_api_key_visibility)
        api_key_layout.addWidget(QLabel("API 키:"))
        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.api_key_toggle)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["선택", "원래 이름", "제안 이름"])
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSortingEnabled(True)

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

        tag_layout = QHBoxLayout()
        self.engine_input = QLineEdit()
        self.engine_input.setPlaceholderText("엔진 태그 입력 (예: 쯔꾸르)")
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("세부 태그 입력 (예: NTR, Z 등)")
        self.tag_apply_btn = QPushButton("선택 항목 태그 수정")
        tag_layout.addWidget(self.engine_input)
        tag_layout.addWidget(self.tag_input)
        tag_layout.addWidget(self.tag_apply_btn)

        self.log_label = QLabel("대기 중입니다.")

        main_layout.addLayout(top_layout)
        main_layout.addLayout(api_key_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(bottom_layout)
        main_layout.addLayout(tag_layout)
        main_layout.addWidget(self.log_label)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        self.select_btn.clicked.connect(self.select_folder)
        self.analyze_btn.clicked.connect(self.analyze_with_ai)
        self.rename_btn.clicked.connect(self.rename_files)
        self.select_all_box.toggled.connect(self.toggle_all_selection)
        self.tag_apply_btn.clicked.connect(self.apply_tag_edit)
        self.gpt_tag_btn.clicked.connect(self.fill_blank_tags_with_gpt)
        self.dlsite_btn.clicked.connect(self.search_dlsite)

        self.folder_path = None
        self.worker = None

    def toggle_api_key_visibility(self):
        if self.api_key_toggle.isChecked():
            self.api_key_input.setEchoMode(QLineEdit.Normal)
            self.api_key_toggle.setText("🙈")
        else:
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.api_key_toggle.setText("👁️")

    def get_openai_client(self):
        api_key = self.api_key_input.text().strip()
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            QMessageBox.critical(self, "오류", "OpenAI API 키를 입력하거나 환경 변수에 설정하세요!")
            return None
        try:
            return OpenAI(api_key=api_key)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"OpenAI 클라이언트 초기화 실패: {str(e)}")
            return None

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.log_label.setText(f"캐시 로드 오류: {str(e)}")
            logging.error(f"Cache load error: {str(e)}")
            return {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_label.setText(f"캐시 저장 오류: {str(e)}")
            logging.error(f"Cache save error: {str(e)}")

    def get_dlsite_data(self, rj_code):
        if rj_code in self.cache:
            return self.cache[rj_code]

        try:
            url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('h1', id='work_name')
            if not title_tag:
                return None

            title = title_tag.text.strip()
            tags = [tag.text.strip() for tag in soup.find_all('span', class_='gtag') if tag.text.strip()]
            maker = soup.find('span', class_='maker_name')
            maker = maker.text.strip() if maker else ""
            release_date = soup.find('th', string='販売日')
            release_date = release_date.find_next('td').text.strip() if release_date else ""

            engine = rj_code
            if any("RPG" in tag or "쯔꾸르" in tag for tag in tags):
                engine = "쯔꾸르"
            elif any("렌파이" in tag or "Ren'Py" in tag for tag in tags):
                engine = "렌파이"

            data = {
                "title": title,
                "engine": engine,
                "tag": tags[0] if tags else "",
                "maker": maker,
                "release_date": release_date
            }
            self.cache[rj_code] = data
            self.save_cache()
            time.sleep(1)
            return data
        except Exception as e:
            self.log_label.setText(f"DLsite 검색 오류 (RJ{rj_code}): {str(e)}")
            logging.error(f"DLsite error (RJ{rj_code}): {str(e)}")
            return None

    def toggle_all_selection(self, checked):
        self.log_label.setText("전체 선택 상태 변경 중...")
        logging.info(f"toggle_all_selection: checked={checked}, rowCount={self.table.rowCount()}")

        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox):
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
                chk.update()
                logging.info(f"Row {row}: Checkbox set to {chk.isChecked()}")
        self.table.setUpdatesEnabled(True)

        self.table.viewport().update()
        QApplication.processEvents()
        self.log_label.setText(f"전체 선택 {'완료' if checked else '해제'}")
        self.update_select_all_state()

    def update_select_all_state(self):
        if self.table.rowCount() == 0:
            self.select_all_box.blockSignals(True)
            self.select_all_box.setChecked(False)
            self.select_all_box.setEnabled(False)
            self.select_all_box.blockSignals(False)
            logging.info("update_select_all_state: Table is empty")
            return

        all_checked = True
        none_checked = True
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox):
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
        logging.info(f"update_select_all_state: all_checked={all_checked}, none_checked={none_checked}")

    def select_folder(self):
        self.folder_path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not self.folder_path:
            return

        self.log_label.setText("폴더 스캔 중...")
        logging.info("Scanning folder")
        self.table.setRowCount(0)
        self.results.clear()

        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]

        self.table.setUpdatesEnabled(False)
        for idx, original in enumerate(files):
            rj_match = re.search(r"RJ\d{6,8}", original, re.IGNORECASE)
            suggested = f"[{rj_match.group(0)}][기타]{original}" if rj_match else f"[기타][기타]{original}"

            result = {
                "original": original,
                "suggested": suggested,
                "path": os.path.join(self.folder_path, original)
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.table.insertRow(idx)
            self.table.setCellWidget(idx, 0, chk)
            self.table.setItem(idx, 1, QTableWidgetItem(original))
            self.table.setItem(idx, 2, QTableWidgetItem(suggested))
            logging.info(f"Added row {idx}: {original}")

        self.table.setUpdatesEnabled(True)
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.progress_bar.setValue(0)
        self.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
        logging.info(f"Folder loaded: {len(self.results)} files")
        self.update_select_all_state()

    def on_checkbox_changed(self, row, checked):
        logging.info(f"Checkbox changed: row={row}, checked={checked}")
        self.update_select_all_state()

    def search_dlsite(self):
        if not self.folder_path:
            QMessageBox.warning(self, "오류", "폴더를 먼저 선택하세요!")
            return

        self.log_label.setText("DLsite에서 데이터 가져오는 중...")
        logging.info("Starting DLsite search")
        self.progress_bar.setValue(0)
        total = len(self.results)
        updated = 0

        for i, result in enumerate(self.results):
            self.progress_bar.setValue(int((i + 1) / total * 100))
            original = result['original']
            rj_match = re.search(r"RJ\d{6,8}", original, re.IGNORECASE)
            if not rj_match:
                continue

            rj_code = rj_match.group(0)
            self.log_label.setText(f"DLsite 검색: {rj_code}")
            data = self.get_dlsite_data(rj_code)
            if not data:
                continue

            new_name = f"[{data['engine']}][{data['tag']}]{data['title']}"
            if result['suggested'] != new_name:
                result['suggested'] = new_name
                self.table.setItem(i, 2, QTableWidgetItem(new_name))
                updated += 1

        self.progress_bar.setValue(100)
        self.log_label.setText(f"DLsite 검색 완료: {updated}개 항목 업데이트됨.")
        logging.info(f"DLsite search completed: {updated} items updated")
        self.update_select_all_state()

    def analyze_with_ai(self):
        if not self.folder_path:
            QMessageBox.warning(self, "오류", "폴더를 먼저 선택하세요!")
            return

        self.client = self.get_openai_client()
        if not self.client:
            return

        self.log_label.setText("파일 목록 로드 중...")
        logging.info("Loading file list")
        self.progress_bar.setValue(0)

        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]
        total_files = len(files)

        enhanced_files = []
        for i, f in enumerate(files):
            self.progress_bar.setValue(int((i + 1) / total_files * 33))
            self.log_label.setText(f"파일 처리 중: {f}")
            rj_match = re.search(r"(RJ\d{6,8})", f, re.IGNORECASE)
            if rj_match:
                rj_code = rj_match.group(1)
                self.log_label.setText(f"DLsite 검색: {rj_code}")
                data = self.get_dlsite_data(rj_code)
                if data:
                    enhanced_files.append(f"{rj_code}_{data['title']}")
                else:
                    enhanced_files.append(f)
            else:
                enhanced_files.append(f)

        self.analyze_btn.setEnabled(False)
        self.gpt_tag_btn.setEnabled(False)

        self.worker = GPTWorker(self.client, files, enhanced_files, batch_size=10)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_label.setText)
        self.worker.result.connect(lambda answer: self.on_analyze_finished(answer, files))
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_analyze_finished(self, answer, files):
        self.log_label.setText("테이블 업데이트 중...")
        logging.info("Updating table")
        self.progress_bar.setValue(75)

        self.table.setRowCount(0)
        self.results.clear()

        self.table.setUpdatesEnabled(False)
        for idx, (original, line) in enumerate(zip(files, answer)):
            suggested = line.strip()
            result = {
                "original": original,
                "suggested": suggested,
                "path": os.path.join(self.folder_path, original)
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.table.insertRow(idx)
            self.table.setCellWidget(idx, 0, chk)
            self.table.setItem(idx, 1, QTableWidgetItem(original))
            self.table.setItem(idx, 2, QTableWidgetItem(suggested))
            logging.info(f"Added row {idx}: {original}")

        self.table.setUpdatesEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"AI 분석 완료: {len(self.results)}개 파일 처리됨.")
        logging.info(f"AI analysis completed: {len(self.results)} files")
        self.update_select_all_state()

    def fill_blank_tags_with_gpt(self):
        if not self.results:
            QMessageBox.warning(self, "오류", "먼저 폴더를 선택하고 파일을 로드하세요!")
            return

        self.client = self.get_openai_client()
        if not self.client:
            return

        self.log_label.setText("빈 태그/엔진 GPT 보완 중...")
        logging.info("Starting tag completion")
        self.progress_bar.setValue(0)

        self.analyze_btn.setEnabled(False)
        self.gpt_tag_btn.setEnabled(False)

        self.worker = TagWorker(self.client, self.results, batch_size=10)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_label.setText)
        self.worker.result.connect(self.on_tag_fill_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_tag_fill_finished(self, updated_results):
        self.progress_bar.setValue(100)
        self.results = updated_results
        self.table.setRowCount(0)

        self.table.setUpdatesEnabled(False)
        for idx, result in enumerate(self.results):
            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.table.insertRow(idx)
            self.table.setCellWidget(idx, 0, chk)
            self.table.setItem(idx, 1, QTableWidgetItem(result['original']))
            self.table.setItem(idx, 2, QTableWidgetItem(result['suggested']))
            logging.info(f"Updated row {idx}: {result['original']}")
        self.table.setUpdatesEnabled(True)

        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"GPT 태그 보완 완료: {len(self.results)}개 항목 처리됨.")
        logging.info(f"Tag completion completed: {len(self.results)} items")
        self.update_select_all_state()

    def on_worker_error(self, error):
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "OpenAI 오류", error)
        self.log_label.setText("작업 중 오류 발생")
        logging.error(f"Worker error: {error}")

    def on_worker_finished(self):
        self.analyze_btn.setEnabled(True)
        self.gpt_tag_btn.setEnabled(True)
        self.worker = None
        self.log_label.setText("작업 완료")
        logging.info("Worker finished")

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
        logging.info("Starting file rename")
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

            if new_name == original_name or new_name.startswith("[오류]"):
                continue

            new_path = os.path.join(self.folder_path, new_name)
            new_path = self.get_unique_path(new_path)

            try:
                self.log_label.setText(f"이름 변경: {original_name} → {new_name}")
                os.rename(original_path, new_path)
                self.results[row]['path'] = new_path
                completed += 1
                self.status_label.setText(f"파일: {total}개")
            except Exception as e:
                errors.append(f"{original_path}: {e}")

        self.progress_bar.setValue(100)
        if errors:
            QMessageBox.warning(self, "오류", f"다음 파일 이름 변경 실패:\n" + "\n".join(errors[:5]))
        self.log_label.setText(f"이름 변경 완료: {completed}개 파일 변경됨.")
        logging.info(f"Rename completed: {completed} files renamed")
        self.update_select_all_state()

    def apply_tag_edit(self):
        engine = self.engine_input.text().strip()
        tag = self.tag_input.text().strip()

        if not engine and not tag:
            QMessageBox.warning(self, "입력 오류", "엔진 또는 태그 중 하나 이상을 입력하세요.")
            return

        self.log_label.setText("태그 수정 적용 중...")
        logging.info("Applying tag edits")
        self.progress_bar.setValue(0)
        total = self.table.rowCount()
        updated = 0

        for i in range(total):
            self.progress_bar.setValue(int((i + 1) / total * 100))
            if not self.table.cellWidget(i, 0).isChecked():
                continue

            current = self.results[i]['suggested']
            match = re.match(r"\[(.*?)\]\[(.*?)\](.+)", current)
            if match:
                current_engine, current_tag, title = match.groups()
                new_engine = engine if engine else current_engine
                new_tag = tag if tag else current_tag
                new_name = f"[{new_engine}][{new_tag}]{title}"
                self.results[i]['suggested'] = new_name
                self.table.setItem(i, 2, QTableWidgetItem(new_name))
                updated += 1

        self.progress_bar.setValue(100)
        self.log_label.setText(f"태그 수정 완료: {updated}개 항목 수정됨.")
        logging.info(f"Tag edits applied: {updated} items updated")
        self.update_select_all_state()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
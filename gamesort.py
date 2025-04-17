import sys
import os
import re
import json
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
            if total_files == 0:
                self.log.emit("처리할 파일이 없습니다.")
                logging.error("No files to process")
                self.result.emit([])
                return

            logging.info(f"Starting GPT processing for {total_files} files")
            result_queue = Queue()
            batches = [self.files[i:i + self.batch_size] for i in range(0, total_files, self.batch_size)]
            enhanced_batches = [self.enhanced_files[i:i + self.batch_size] for i in range(0, total_files, self.batch_size)]
            total_batches = len(batches)
            self.log.emit(f"총 {total_batches}개 배치로 처리 시작")

            def process_batch(batch_idx, batch_files, batch_enhanced):
                try:
                    if not batch_files or not batch_enhanced:
                        logging.error(f"Batch {batch_idx + 1}: Empty files or enhanced data")
                        return batch_idx, [f"[기타][기타]{f}" for f in batch_files]

                    file_prompts = []
                    for i, (original, enhanced) in enumerate(zip(batch_files, batch_enhanced)):
                        rj_code = enhanced.get('rj_code', '없음')
                        title = enhanced.get('title', original)
                        # DLsite 제목이 RJ 코드와 같거나 비어 있으면 원본 파일명 사용
                        if title == rj_code or not title.strip():
                            title = original
                            logging.warning(f"Batch {batch_idx + 1}: DLsite title invalid for {original}, using original filename")
                        tags = ', '.join(enhanced.get('tags', [])) or '없음'
                        file_prompts.append(
                            f"{i+1}. 원본파일명: {original}, RJ코드: {rj_code}, DLsite제목: {title}, 태그: {tags}"
                        )
                    logging.info(f"Batch {batch_idx + 1}: File prompts: {file_prompts}")

                    prompt_text = (
                        "다음은 일본 게임 압축파일의 정보 목록입니다.\n"
                        "각 정보를 기반으로 아래 규칙에 따라 새 파일명을 제안해 주세요:\n"
                        "1. 모든 태그는 대괄호 [ ] 안에 표기합니다.\n"
                        "2. 첫 번째 태그는 파일 정보에 따라 다음 중 하나를 선택합니다:\n"
                        "   - RJ코드가 있으면: [RJ123456]처럼 정확히 표기합니다.\n"
                        "   - '렌파이', '쯔꾸르'가 DLsite제목이나 태그에 있으면: [렌파이], [쯔꾸르].\n"
                        "   - 그 외: [기타].\n"
                        "   ⚠️ [RJ없음], [RJ코드], [분류없음] 같은 태그는 절대 사용하지 마세요. [기타]로 통일하세요.\n"
                        "3. 두 번째 태그는 장르 키워드를 한국어로 넣습니다:\n"
                        "   - 태그에 명확한 장르가 있으면 이를 한국어로 변환: 예, '日常/生活'→[일상], 'RPG'→[RPG], 'ラブラブ/あまあま'→[순애], '露出'→[노출].\n"
                        "   - 'ビッチ'는 [NTR]로 간주하지 말고 [기타]로 처리.\n"
                        "   - 장르가 불명확하면 [기타].\n"
                        "4. 제목 정리 규칙:\n"
                        "   - DLsite제목이 제공되면 **반드시** 이를 한국어로 번역하여 사용하세요(고유명사는 유지).\n"
                        "     예: 家出少女との同棲生活 → 가출소녀와의동거생활\n"
                        "     예: ねるこはそだつ! → 네루코는자란다!\n"
                        "   - DLsite제목이 원본파일명이나 RJ코드와 동일하면 원본파일명을 참조하되, 의미 있는 제목을 추출하세요.\n"
                        "   - 원본파일명이 RJ코드만 포함(예: RJ01048422.zip)이고 DLsite제목이 있으면 DLsite제목을 번역하세요.\n"
                        "   - 번역은 직역 중심으로, 자연스럽게 다듬되 원문 의미를 살려야 합니다.\n"
                        "   - 특수문자(?, *, :, <, >, /, \\, |)는 제거하고, ?는 ,로 대체하세요.\n"
                        "5. 출력 형식: [분류][태그]정리된제목.기존파일확장자\n"
                        "   - 번호 없이, 한 줄씩 결과만 출력하세요.\n"
                        "   - 각 파일에 대해 정확히 하나의 제안 이름을 반환하세요.\n"
                        "입력 예시:\n"
                        "1. 원본파일명: RJ01048422.zip, RJ코드: RJ01048422, DLsite제목: 家出少女との同棲生活, 태그: 日常/生活\n"
                        "출력 예시:\n"
                        "[RJ01048422][일상]가출소녀와의동거생활.zip\n"
                        "입력:\n" + "\n".join(file_prompts)
                    )
                    logging.info(f"Batch {batch_idx + 1}: Full prompt: {prompt_text}")

                    self.log.emit(f"배치 {batch_idx + 1}/{total_batches} 처리 중...")
                    logging.info(f"Processing batch {batch_idx + 1}/{total_batches}")

                    for attempt in range(3):
                        try:
                            response = self.client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[
                                    {"role": "system", "content": "당신은 일본어 게임 파일 이름을 한국어로 정리하는 전문가입니다. 주어진 지침을 엄격히 따라 정확한 번역과 형식을 제공하세요."},
                                    {"role": "user", "content": prompt_text}
                                ],
                                temperature=0.1
                            )
                            answer = response.choices[0].message.content.strip().splitlines()
                            # 응답 검증
                            if not answer or len(answer) != len(batch_files):
                                logging.warning(f"Batch {batch_idx + 1}: Invalid GPT response length: {len(answer)} vs {len(batch_files)}")
                                answer = [f"[기타][기타]{f}" for f in batch_files]
                            for line in answer:
                                if not re.match(r"\[.*?\]\[.*?\].+\..+", line):
                                    logging.warning(f"Batch {batch_idx + 1}: Invalid GPT response format: {line}")
                            logging.info(f"Batch {batch_idx + 1}: GPT response: {answer}")
                            return batch_idx, answer
                        except Exception as e:
                            logging.error(f"Batch {batch_idx + 1}: API call failed: {str(e)}")
                            if "429" in str(e):
                                self.log.emit(f"배치 {batch_idx + 1} 재시도 {attempt + 1}/3...")
                                time.sleep(2 ** attempt)
                            else:
                                raise
                    logging.error(f"Batch {batch_idx + 1}: API call failed after 3 attempts")
                    return batch_idx, [f"[기타][기타]{f}" for f in batch_files]
                except Exception as e:
                    self.log.emit(f"배치 {batch_idx + 1} 오류: {str(e)}")
                    logging.error(f"Batch {batch_idx + 1} error: {str(e)}")
                    return batch_idx, [f"[기타][기타]{f}" for f in batch_files]

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

            final_results = []
            while not result_queue.empty():
                batch_idx, batch_result = result_queue.get()
                final_results.append((batch_idx, batch_result))

            final_results.sort()
            answer = []
            for _, batch_result in final_results:
                answer.extend(batch_result)

            self.result.emit(answer)
            self.progress.emit(100)
            self.log.emit("GPT 분석 완료")
            logging.info(f"GPT 분석 완료: {len(answer)}개 파일, 소요 시간: {time.time() - start_time:.2f}초")
        except Exception as e:
            self.error.emit(str(e))
            logging.error(f"GPTWorker error: {str(e)}")
        finally:
            self.finished.emit()

class ReanalyzeWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, client, indices, results, batch_size=10):
        super().__init__()
        self.client = client
        self.indices = indices
        self.results = results
        self.batch_size = batch_size

    def run(self):
        try:
            total_files = len(self.indices)
            if total_files == 0:
                self.log.emit("재분석할 파일이 없습니다.")
                logging.error("No files to reanalyze")
                self.result.emit([])
                return

            logging.info(f"Starting reanalysis for {total_files} files")
            result_queue = Queue()
            batches = [self.indices[i:i + self.batch_size] for i in range(0, total_files, self.batch_size)]
            total_batches = len(batches)
            self.log.emit(f"총 {total_batches}개 배치로 재분석 시작")

            def process_batch(batch_idx, batch_indices):
                try:
                    if not batch_indices:
                        logging.error(f"Batch {batch_idx + 1}: Empty indices")
                        return batch_idx, []

                    file_prompts = []
                    for i, idx in enumerate(batch_indices):
                        result = self.results[idx]
                        original = result['original']
                        suggested = result['suggested']
                        rj_match = re.search(r"RJ\d{6,8}", original, re.IGNORECASE)
                        rj_code = rj_match.group(0) if rj_match else '없음'
                        file_prompts.append(
                            f"{i+1}. 원본파일명: {original}, 현재제안: {suggested}, RJ코드: {rj_code}"
                        )
                    logging.info(f"Batch {batch_idx + 1}: Sending to GPT for reanalysis: {file_prompts}")

                    prompt_text = (
                        "다음은 게임 압축파일의 현재 제안 이름 목록입니다.\n"
                        "각 이름을 검토해 아래 규칙으로 새 이름을 제안하세요:\n"
                        "1. 모든 태그는 대괄호 [ ] 안에 표기합니다.\n"
                        "2. 첫 번째 태그는 다음 중 하나를 선택합니다:\n"
                        "   - RJ코드가 있으면: [RJ123456].\n"
                        "   - '렌파이', '쯔꾸르'가 파일명/현재제안에 있으면: [렌파이], [쯔꾸르].\n"
                        "   - 그 외: [기타].\n"
                        "   ⚠️ [RJ없음], [분류없음] 같은 태그는 절대 사용하지 마세요. [기타]로 통일하세요.\n"
                        "3. 두 번째 태그는 장르 키워드:\n"
                        "   - [청아], [순애], [NTR], [RPG] 등이 현재제안/파일명에 명확히 드러나면 사용.\n"
                        "   - 빼앗는다, 유혹한다 같은 표현은 NTR로 간주하지 마세요.\n"
                        "   - 불명확하면 [기타].\n"
                        "4. 제목 처리:\n"
                        "   - 현재제안에 한국어 제목이 있으면 자연스럽게 개선.\n"
                        "   - 일본어 제목은 한국어로 번역(고유명사 유지).\n"
                        "     예: むすめせいかつ → 딸의생활\n"
                        "   - 특수문자(?, *, :, <, >, /, \\, |) 제거, ?는 ,로.\n"
                        "5. 출력 형식: [분류][태그]정리된제목.기존파일확장자\n"
                        "6. 번호 없이, 한 줄씩 결과만 출력하세요.\n"
                        "입력:\n" + "\n".join(file_prompts)
                    )

                    self.log.emit(f"배치 {batch_idx + 1}/{total_batches} 재분석 중...")
                    logging.info(f"Processing reanalysis batch {batch_idx + 1}/{total_batches}")

                    for attempt in range(3):
                        try:
                            response = self.client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[
                                    {"role": "system", "content": "당신은 압축 게임 파일 이름을 정리하는 전문가입니다."},
                                    {"role": "user", "content": prompt_text}
                                ],
                                temperature=0.2
                            )
                            answer = response.choices[0].message.content.strip().splitlines()
                            logging.info(f"Batch {batch_idx + 1}: GPT reanalysis response: {answer}")
                            return batch_idx, [(i, a) for i, a in zip(batch_indices, answer)]
                        except Exception as e:
                            logging.error(f"Batch {batch_idx + 1}: API call failed: {str(e)}")
                            if "429" in str(e):
                                self.log.emit(f"배치 {batch_idx + 1} 재시도 {attempt + 1}/3...")
                                time.sleep(2 ** attempt)
                            else:
                                raise
                    logging.error(f"Batch {batch_idx + 1}: API call failed after 3 attempts")
                    return batch_idx, [(i, self.results[i]['suggested']) for i in batch_indices]
                except Exception as e:
                    self.log.emit(f"배치 {batch_idx + 1} 오류: {str(e)}")
                    logging.error(f"Batch {batch_idx + 1} error: {str(e)}")
                    return batch_idx, [(i, self.results[i]['suggested']) for i in batch_indices]

            start_time = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(process_batch, i, batch_indices)
                    for i, batch_indices in enumerate(batches)
                ]
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    batch_idx, batch_result = future.result()
                    result_queue.put((batch_idx, batch_result))
                    self.progress.emit(int((i + 1) / total_batches * 50))
                    QApplication.processEvents()

            final_results = []
            while not result_queue.empty():
                batch_idx, batch_result = result_queue.get()
                final_results.append((batch_idx, batch_result))

            final_results.sort()
            answer = []
            for _, batch_result in final_results:
                answer.extend(batch_result)

            self.result.emit(answer)
            self.progress.emit(100)
            self.log.emit("GPT 재분석 완료")
            logging.info(f"GPT 재분석 완료: {len(answer)}개 파일, 소요 시간: {time.time() - start_time:.2f}초")
        except Exception as e:
            self.error.emit(str(e))
            logging.error(f"ReanalyzeWorker error: {str(e)}")
        finally:
            self.finished.emit()

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
        self.reanalyze_btn = QPushButton("\U0001F504 선택 항목 재분석")
        top_layout.addWidget(self.select_btn)
        top_layout.addWidget(self.analyze_btn)
        top_layout.addWidget(self.reanalyze_btn)

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
        self.tag_input.setPlaceholderText("세부 태그 입력 (예: NTR, RPG 등)")
        self.tag_apply_btn = QPushButton("선택 항목 태그 수정")
        tag_layout.addWidget(self.engine_input)
        tag_layout.addWidget(self.tag_input)
        tag_layout.addWidget(self.tag_apply_btn)

        self.log_label = QLabel("대기 중입니다.")

        # 수정: custom_layout이 정의되지 않았으므로 제거하거나 정의 필요
        # main_layout.addLayout(custom_layout) 줄 제거
        main_layout.addLayout(top_layout)
        main_layout.addLayout(api_key_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(bottom_layout)  # 오류 발생 예상
        main_layout.addLayout(tag_layout)
        main_layout.addWidget(self.log_label)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        self.select_btn.clicked.connect(self.select_folder)
        self.analyze_btn.clicked.connect(self.analyze_with_ai)
        self.reanalyze_btn.clicked.connect(self.reanalyze_selected)
        self.rename_btn.clicked.connect(self.rename_files)
        self.select_all_box.toggled.connect(self.toggle_all_selection)
        self.tag_apply_btn.clicked.connect(self.apply_tag_edit)

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
            # 수정: proxies 오류 방지를 위해 http_client=None 추가
            client = OpenAI(api_key=api_key, http_client=None)
            client.models.list()  # API 키 검증
            logging.info("OpenAI client initialized successfully")
            return client
        except Exception as e:
            QMessageBox.critical(self, "오류", f"OpenAI 클라이언트 초기화 실패: {str(e)}")
            logging.error(f"OpenAI client init failed: {str(e)}")
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
            logging.info(f"Cache hit for {rj_code}: {self.cache[rj_code]}")
            return self.cache[rj_code]

        for attempt in range(3):
            try:
                url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.encoding = 'utf-8'

                if response.status_code != 200:
                    logging.error(f"DLsite fetch failed for {rj_code}: Status {response.status_code}")
                    time.sleep(2 ** attempt)
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                title_tag = soup.find('h1', id='work_name') or soup.find('h1', itemprop='name')
                title = title_tag.text.strip() if title_tag else soup.find('meta', property='og:title')['content'].strip() if soup.find('meta', property='og:title') else rj_code

                tags = []
                genre_elements = soup.find_all('a', href=lambda x: x and '/maniax/genre' in x)
                for elem in genre_elements:
                    tag = elem.text.strip()
                    if tag:
                        tags.append(tag)

                maker = soup.find('span', class_='maker_name')
                maker = maker.text.strip() if maker else ""

                engine = rj_code
                if any(tag.lower() in ['rpg', 'ロールプレイング', '쯔꾸르'] for tag in tags):
                    engine = '쯔꾸르'
                elif any(tag.lower() in ['렌파이', "ren'py"] for tag in tags):
                    engine = '렌파이'

                data = {
                    'rj_code': rj_code,
                    'title': title,
                    'tags': tags[:3],
                    'engine': engine,
                    'maker': maker
                }
                self.cache[rj_code] = data
                self.save_cache()
                logging.info(f"Fetched DLsite data for {rj_code}: {data}")
                return data
            except Exception as e:
                logging.error(f"DLsite fetch error for {rj_code}, attempt {attempt + 1}: {str(e)}")
                time.sleep(2 ** attempt)
        logging.error(f"DLsite fetch failed for {rj_code} after 3 attempts")
        data = {
            'rj_code': rj_code,
            'title': rj_code,
            'tags': [],
            'engine': rj_code,
            'maker': ''
        }
        logging.info(f"Returning default data for {rj_code}: {data}")
        return data

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
        files.sort()

        self.table.setUpdatesEnabled(False)
        for idx, original in enumerate(files):
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            suggested = f"[{rj_code}][기타]{original}" if rj_code else f"[기타][기타]{original}"

            result = {
                'original': original,
                'suggested': suggested,
                'path': os.path.join(self.folder_path, original)
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
        files.sort()
        total_files = len(files)
        if not files:
            QMessageBox.warning(self, "오류", "선택한 폴더에 처리할 파일이 없습니다!")
            self.log_label.setText("파일 없음")
            return

        enhanced_files = []
        for i, f in enumerate(files):
            self.progress_bar.setValue(int((i + 1) / total_files * 33))
            self.log_label.setText(f"파일 처리 중: {f}")
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", f, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            data = self.get_dlsite_data(rj_code) if rj_code else None
            enhanced_data = data or {'rj_code': None, 'title': f, 'tags': [], 'engine': '기타', 'maker': ''}
            enhanced_files.append(enhanced_data)
            logging.info(f"Enhanced file for {f}: {enhanced_data}")

        logging.info(f"Starting AI analysis for {total_files} files")
        self.analyze_btn.setEnabled(False)
        self.reanalyze_btn.setEnabled(False)

        self.worker = GPTWorker(self.client, files, enhanced_files, batch_size=10)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_label.setText)
        self.worker.result.connect(lambda answer: self.on_analyze_finished(answer, files))
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def reanalyze_selected(self):
        if not self.results:
            QMessageBox.warning(self, "오류", "먼저 폴더를 선택하고 파일을 로드하세요!")
            return

        self.client = self.get_openai_client()
        if not self.client:
            return

        selected_indices = [i for i in range(self.table.rowCount()) if self.table.cellWidget(i, 0).isChecked()]
        if not selected_indices:
            QMessageBox.warning(self, "오류", "재분석할 항목을 선택하세요!")
            return

        self.log_label.setText("선택 항목 재분석 중...")
        logging.info(f"Reanalyzing {len(selected_indices)} selected items")
        self.progress_bar.setValue(0)

        self.analyze_btn.setEnabled(False)
        self.reanalyze_btn.setEnabled(False)

        self.worker = ReanalyzeWorker(self.client, selected_indices, self.results, batch_size=10)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_label.setText)
        self.worker.result.connect(self.on_reanalyze_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_analyze_finished(self, answer, files):
        self.log_label.setText("테이블 업데이트 중...")
        logging.info("Updating table")
        self.progress_bar.setValue(75)

        if not answer or len(answer) != len(files):
            logging.error(f"Invalid GPT response: {answer}")
            answer = [f"[기타][기타]{f}" for f in files]

        self.table.setRowCount(0)
        self.results.clear()

        self.table.setUpdatesEnabled(False)
        for idx, (original, line) in enumerate(zip(files, answer)):
            suggested = line.strip() if isinstance(line, str) and line.strip() else f"[기타][기타]{original}"
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            if rj_code and not suggested.startswith(f"[{rj_code}]"):
                suggested = f"[{rj_code}][기타]{original}"
                logging.warning(f"Row {idx}: Invalid GPT suggested name for {original}, using fallback: {suggested}")
            result = {
                'original': original,
                'suggested': suggested,
                'path': os.path.join(self.folder_path, original)
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.table.insertRow(idx)
            self.table.setCellWidget(idx, 0, chk)
            self.table.setItem(idx, 1, QTableWidgetItem(original))
            self.table.setItem(idx, 2, QTableWidgetItem(suggested))
            logging.info(f"Added row {idx}: {original} -> {suggested}")

        self.table.setUpdatesEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"AI 분석 완료: {len(self.results)}개 파일 처리됨.")
        logging.info(f"AI analysis completed: {len(self.results)} files")
        self.update_select_all_state()

    def on_reanalyze_finished(self, answer):
        self.log_label.setText("테이블 업데이트 중...")
        logging.info("Updating table for reanalysis")
        self.progress_bar.setValue(75)

        updated = 0
        self.table.setUpdatesEnabled(False)
        for idx, new_suggested in answer:
            new_suggested = new_suggested.strip() if isinstance(new_suggested, str) and new_suggested.strip() else self.results[idx]['suggested']
            if not re.match(r"\[.*?\]\[.*?\].+", new_suggested):
                new_suggested = self.results[idx]['suggested']
                logging.warning(f"Reanalysis row {idx}: Invalid GPT suggested name, keeping original: {new_suggested}")
            if new_suggested != self.results[idx]['suggested']:
                self.results[idx]['suggested'] = new_suggested
                self.table.setItem(idx, 2, QTableWidgetItem(new_suggested))
                updated += 1
            logging.info(f"Reanalyzed row {idx}: {new_suggested}")

        self.table.setUpdatesEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"파일: {len(self.results)}개")
        self.log_label.setText(f"재분석 완료: {updated}개 항목 수정됨.")
        logging.info(f"Reanalysis completed: {updated} items updated")
        self.update_select_all_state()

    def on_worker_error(self, error):
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "오류", f"작업 실패: {error}")
        self.log_label.setText("작업 중 오류 발생")
        logging.error(f"Worker error: {error}")

    def on_worker_finished(self):
        self.analyze_btn.setEnabled(True)
        self.reanalyze_btn.setEnabled(True)
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
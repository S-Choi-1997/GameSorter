import os
import re
import json
import requests
from bs4 import BeautifulSoup
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QCheckBox
from PySide6.QtCore import QThread, Signal
from openai import OpenAI
import time
import concurrent.futures
from queue import Queue
import logging

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
                        title = enhanced.get('title_kr', original)
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
                        "   - DLsite제목이 제공되면 **반드시** 이를 한국어로 사용하세요.\n"
                        "   - DLsite제목이 원본파일명이나 RJ코드와 동일하면 원본파일명을 참조하되, 의미 있는 제목을 추출하세요.\n"
                        "   - 특수문자(?, *, :, <, >, /, \\, |)는 제거하고, ?는 ,로 대체하세요.\n"
                        "5. 출력 형식: [분류][태그]정리된제목.기존파일확장자\n"
                        "   - 번호 없이, 한 줄씩 결과만 출력하세요.\n"
                        "   - 각 파일에 대해 정확히 하나의 제안 이름을 반환하세요.\n"
                        "입력 예시:\n"
                        "1. 원본파일명: RJ01048422.zip, RJ코드: RJ01048422, DLsite제목: 가출소녀와의동거생활, 태그: 일상\n"
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
                                    {"role": "system", "content": "당신은 일본어 게임 파일 이름을 한국어로 정리하는 전문가입니다."},
                                    {"role": "user", "content": prompt_text}
                                ],
                                temperature=0.1
                            )
                            answer = response.choices[0].message.content.strip().splitlines()
                            if not answer or len(answer) != len(batch_files):
                                logging.warning(f"Batch {batch_idx + 1}: Invalid GPT response length")
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
                        "   - 불명확하면 [기타].\n"
                        "4. 제목 처리:\n"
                        "   - 현재제안에 한국어 제목이 있으면 자연스럽게 개선.\n"
                        "   - 일본어 제목은 한국어로 번역(고유명사 유지).\n"
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

class MainWindowLogic:
    def __init__(self, ui):
        self.ui = ui
        self.results = []
        self.cache_file = "dlsite_cache.json"
        self.cache = self.load_cache()
        self.client = None
        self.folder_path = None
        self.worker = None
        self.SERVER_URL = "https://rj-server-xxx.a.run.app"  # 실제 Cloud Run URL로 변경

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.ui.log_label.setText(f"캐시 로드 오류: {str(e)}")
            logging.error(f"Cache load error: {str(e)}")
            return {}

    def save_cache(self, data):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.ui.log_label.setText(f"캐시 저장 오류: {str(e)}")
            logging.error(f"Cache save error: {str(e)}")

    def get_dlsite_data(self, rj_code):
        if not rj_code:
            return None
        if rj_code in self.cache:
            logging.info(f"Cache hit for {rj_code}")
            return self.cache[rj_code]

        try:
            response = requests.get(f"{self.SERVER_URL}/rj/{rj_code}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.cache[rj_code] = data
                self.save_cache(self.cache)
                logging.info(f"Fetched data for {rj_code}: {data}")
                return data
            logging.error(f"Server fetch failed for {rj_code}: Status {response.status_code}")
        except Exception as e:
            logging.error(f"Server fetch error for {rj_code}: {str(e)}")
        return None

    def get_openai_client(self):
        api_key = self.ui.api_key_input.text().strip()
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            QMessageBox.critical(self.ui, "오류", "OpenAI API 키를 입력하거나 환경 변수에 설정하세요!")
            return None
        try:
            client = OpenAI(api_key=api_key, http_client=None)
            client.models.list()
            logging.info("OpenAI client initialized")
            return client
        except Exception as e:
            QMessageBox.critical(self.ui, "오류", f"OpenAI 클라이언트 초기화 실패: {str(e)}")
            logging.error(f"OpenAI client init failed: {str(e)}")
            return None

    def select_folder(self):
        self.folder_path = QFileDialog.getExistingDirectory(self.ui, "폴더 선택")
        if not self.folder_path:
            return

        self.ui.log_label.setText("폴더 스캔 중...")
        logging.info("Scanning folder")
        self.ui.table.setRowCount(0)
        self.results.clear()

        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]
        files.sort()

        self.ui.table.setUpdatesEnabled(False)
        for idx, original in enumerate(files):
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            suggested = f"[{rj_code}][기타]{original}" if rj_code else f"[기타][기타]{original}"

            result = {
                'original': original,
                'suggested': suggested,
                'path': os.path.join(self.folder_path, original),
                'rj_code': rj_code
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.ui.table.insertRow(idx)
            self.ui.table.setCellWidget(idx, 0, chk)
            self.ui.table.setItem(idx, 1, QTableWidgetItem(original))
            self.ui.table.setItem(idx, 2, QTableWidgetItem(suggested))
            logging.info(f"Added row {idx}: {original}")

        self.ui.table.setUpdatesEnabled(True)
        self.ui.status_label.setText(f"파일: {len(self.results)}개")
        self.ui.log_label.setText(f"폴더 로드 완료: {len(self.results)}개 파일")
        self.update_select_all_state()

    def on_checkbox_changed(self, row, checked):
        logging.info(f"Checkbox changed: row={row}, checked={checked}")
        self.update_select_all_state()

    def on_table_cell_clicked(self, row, column):
        rj_code = self.results[row]['rj_code']
        if rj_code:
            self.ui.game_data_panel.load_game_data(rj_code)

    def update_select_all_state(self):
        if self.ui.table.rowCount() == 0:
            self.ui.select_all_box.blockSignals(True)
            self.ui.select_all_box.setChecked(False)
            self.ui.select_all_box.setEnabled(False)
            self.ui.select_all_box.blockSignals(False)
            return

        all_checked = True
        none_checked = True
        for row in range(self.ui.table.rowCount()):
            chk = self.ui.table.cellWidget(row, 0)
            if chk.isChecked():
                none_checked = False
            else:
                all_checked = False

        self.ui.select_all_box.blockSignals(True)
        self.ui.select_all_box.setEnabled(True)
        if all_checked:
            self.ui.select_all_box.setChecked(True)
        elif none_checked:
            self.ui.select_all_box.setChecked(False)
        else:
            self.ui.select_all_box.setTristate(True)
            self.ui.select_all_box.setCheckState(Qt.CheckState.PartiallyChecked)
        self.ui.select_all_box.blockSignals(False)

    def toggle_all_selection(self, checked):
        self.ui.log_label.setText("전체 선택 상태 변경 중...")
        self.ui.table.setUpdatesEnabled(False)
        for row in range(self.ui.table.rowCount()):
            chk = self.ui.table.cellWidget(row, 0)
            chk.setChecked(checked)
        self.ui.table.setUpdatesEnabled(True)
        self.ui.log_label.setText(f"전체 선택 {'완료' if checked else '해제'}")
        self.update_select_all_state()

    def analyze_with_ai(self):
        if not self.folder_path:
            QMessageBox.warning(self.ui, "오류", "폴더를 먼저 선택하세요!")
            return

        self.client = self.get_openai_client()
        if not self.client:
            return

        self.ui.log_label.setText("파일 목록 로드 중...")
        self.ui.progress_bar.setValue(0)

        entries = os.listdir(self.folder_path)
        files = [f for f in entries if f.lower().endswith(('.zip', '.7z', '.rar')) or os.path.isdir(os.path.join(self.folder_path, f))]
        files.sort()
        total_files = len(files)
        if not files:
            QMessageBox.warning(self.ui, "오류", "선택한 폴더에 처리할 파일이 없습니다!")
            self.ui.log_label.setText("파일 없음")
            return

        enhanced_files = []
        for i, f in enumerate(files):
            self.ui.progress_bar.setValue(int((i + 1) / total_files * 33))
            self.ui.log_label.setText(f"파일 처리 중: {f}")
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", f, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            data = self.get_dlsite_data(rj_code) if rj_code else None
            enhanced_data = data or {
                'rj_code': None,
                'title_kr': f,
                'tags': [],
                'release_date': '',
                'thumbnail_url': '',
                'translated': False
            }
            enhanced_data['tags'] = [tag['tag_kr'] for tag in enhanced_data.get('tags', [])]
            enhanced_files.append(enhanced_data)

        self.ui.analyze_btn.setEnabled(False)
        self.ui.reanalyze_btn.setEnabled(False)

        self.worker = GPTWorker(self.client, files, enhanced_files, batch_size=10)
        self.worker.progress.connect(self.ui.progress_bar.setValue)
        self.worker.log.connect(self.ui.log_label.setText)
        self.worker.result.connect(lambda answer: self.on_analyze_finished(answer, files))
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def reanalyze_selected(self):
        if not self.results:
            QMessageBox.warning(self.ui, "오류", "먼저 폴더를 선택하고 파일을 로드하세요!")
            return

        self.client = self.get_openai_client()
        if not self.client:
            return

        selected_indices = [i for i in range(self.ui.table.rowCount()) if self.ui.table.cellWidget(i, 0).isChecked()]
        if not selected_indices:
            QMessageBox.warning(self.ui, "오류", "재분석할 항목을 선택하세요!")
            return

        self.ui.log_label.setText("선택 항목 재분석 중...")
        self.ui.progress_bar.setValue(0)

        self.ui.analyze_btn.setEnabled(False)
        self.ui.reanalyze_btn.setEnabled(False)

        self.worker = ReanalyzeWorker(self.client, selected_indices, self.results, batch_size=10)
        self.worker.progress.connect(self.ui.progress_bar.setValue)
        self.worker.log.connect(self.ui.log_label.setText)
        self.worker.result.connect(self.on_reanalyze_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_analyze_finished(self, answer, files):
        self.ui.log_label.setText("테이블 업데이트 중...")
        self.ui.progress_bar.setValue(75)

        if not answer or len(answer) != len(files):
            answer = [f"[기타][기타]{f}" for f in files]

        self.ui.table.setRowCount(0)
        self.results.clear()

        self.ui.table.setUpdatesEnabled(False)
        for idx, (original, line) in enumerate(zip(files, answer)):
            suggested = line.strip() if isinstance(line, str) and line.strip() else f"[기타][기타]{original}"
            rj_match = re.search(r"[Rr][Jj][_\-\s]?\d{6,8}", original, re.IGNORECASE)
            rj_code = rj_match.group(0).upper().replace('_', '').replace('-', '') if rj_match else None
            if rj_code and not suggested.startswith(f"[{rj_code}]"):
                suggested = f"[{rj_code}][기타]{original}"
            result = {
                'original': original,
                'suggested': suggested,
                'path': os.path.join(self.folder_path, original),
                'rj_code': rj_code
            }
            self.results.append(result)

            chk = QCheckBox()
            chk.toggled.connect(lambda checked, row=idx: self.on_checkbox_changed(row, checked))
            self.ui.table.insertRow(idx)
            self.ui.table.setCellWidget(idx, 0, chk)
            self.ui.table.setItem(idx, 1, QTableWidgetItem(original))
            self.ui.table.setItem(idx, 2, QTableWidgetItem(suggested))

        self.ui.table.setUpdatesEnabled(True)
        self.ui.progress_bar.setValue(100)
        self.ui.status_label.setText(f"파일: {len(self.results)}개")
        self.ui.log_label.setText(f"AI 분석 완료: {len(self.results)}개 파일 처리됨.")
        self.update_select_all_state()

    def on_reanalyze_finished(self, answer):
        self.ui.log_label.setText("테이블 업데이트 중...")
        self.ui.progress_bar.setValue(75)

        updated = 0
        self.ui.table.setUpdatesEnabled(False)
        for idx, new_suggested in answer:
            new_suggested = new_suggested.strip() if isinstance(new_suggested, str) else self.results[idx]['suggested']
            if not re.match(r"\[.*?\]\[.*?\].+", new_suggested):
                new_suggested = self.results[idx]['suggested']
            if new_suggested != self.results[idx]['suggested']:
                self.results[idx]['suggested'] = new_suggested
                self.ui.table.setItem(idx, 2, QTableWidgetItem(new_suggested))
                updated += 1

        self.ui.table.setUpdatesEnabled(True)
        self.ui.progress_bar.setValue(100)
        self.ui.status_label.setText(f"파일: {len(self.results)}개")
        self.ui.log_label.setText(f"재분석 완료: {updated}개 항목 수정됨.")
        self.update_select_all_state()

    def on_worker_error(self, error):
        self.ui.progress_bar.setValue(0)
        QMessageBox.critical(self.ui, "오류", f"작업 실패: {error}")
        self.ui.log_label.setText("작업 중 오류 발생")

    def on_worker_finished(self):
        self.ui.analyze_btn.setEnabled(True)
        self.ui.reanalyze_btn.setEnabled(True)
        self.worker = None
        self.ui.log_label.setText("작업 완료")

    def get_unique_path(self, new_path):
        base, ext = os.path.splitext(new_path)
        counter = 1
        while os.path.exists(new_path):
            new_path = f"{base}_{counter}{ext}"
            counter += 1
        return new_path

    def rename_files(self):
        total = self.ui.table.rowCount()
        self.ui.progress_bar.setValue(0)
        self.ui.log_label.setText("파일 이름 변경 중...")
        completed = 0
        errors = []

        for row in range(total):
            self.ui.progress_bar.setValue(int((row + 1) / total * 100))
            chk = self.ui.table.cellWidget(row, 0)
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
                self.ui.log_label.setText(f"이름 변경: {original_name} → {new_name}")
                os.rename(original_path, new_path)
                self.results[row]['path'] = new_path
                completed += 1
                self.ui.status_label.setText(f"파일: {total}개")
            except Exception as e:
                errors.append(f"{original_path}: {e}")

        self.ui.progress_bar.setValue(100)
        if errors:
            QMessageBox.warning(self.ui, "오류", f"다음 파일 이름 변경 실패:\n" + "\n".join(errors[:5]))
        self.ui.log_label.setText(f"이름 변경 완료: {completed}개 파일 변경됨.")
        self.update_select_all_state()

    def apply_tag_edit(self):
        engine = self.ui.engine_input.text().strip()
        tag = self.ui.tag_input.text().strip()

        if not engine and not tag:
            QMessageBox.warning(self.ui, "입력 오류", "엔진 또는 태그 중 하나 이상을 입력하세요.")
            return

        self.ui.log_label.setText("태그 수정 적용 중...")
        self.ui.progress_bar.setValue(0)
        total = self.ui.table.rowCount()
        updated = 0

        for i in range(total):
            self.ui.progress_bar.setValue(int((i + 1) / total * 100))
            if not self.ui.table.cellWidget(i, 0).isChecked():
                continue

            current = self.results[i]['suggested']
            match = re.match(r"\[(.*?)\]\[(.*?)\](.+)", current)
            if match:
                current_engine, current_tag, title = match.groups()
                new_engine = engine if engine else current_engine
                new_tag = tag if tag else current_tag
                new_name = f"[{new_engine}][{new_tag}]{title}"
                self.results[i]['suggested'] = new_name
                self.ui.table.setItem(i, 2, QTableWidgetItem(new_name))
                updated += 1

        self.ui.progress_bar.setValue(100)
        self.ui.log_label.setText(f"태그 수정 완료: {updated}개 항목 수정됨.")
        self.update_select_all_state()
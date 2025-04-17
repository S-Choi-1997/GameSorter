import requests
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QPixmap, QImage
from io import BytesIO
import logging

class GameDataPanel:
    def __init__(self, ui):
        self.ui = ui
        self.SERVER_URL = "https://rj-server-xxx.a.run.app"  # 실제 Cloud Run URL로 변경

    def load_game_data(self, rj_code):
        try:
            response = requests.get(f"{self.SERVER_URL}/rj/{rj_code}", timeout=5)
            if response.status_code != 200:
                self.ui.log_label.setText(f"데이터 로드 실패: RJ{rj_code}")
                return

            data = response.json()
            self.ui.title_label.setText(f"제목: {data.get('title_kr', 'N/A')}")
            self.ui.release_date_label.setText(f"출시일: {data.get('release_date', 'N/A')}")
            self.ui.translated_label.setText(f"번역 상태: {'완료' if data.get('translated', False) else '미완료'}")
            tags = ", ".join([tag['tag_kr'] for tag in data.get('tags', [])])
            self.ui.tags_label.setPlainText(tags if tags else "N/A")

            # 썸네일 로드
            thumbnail_url = data.get('thumbnail_url', '')
            if thumbnail_url:
                img_response = requests.get(thumbnail_url, timeout=5)
                if img_response.status_code == 200:
                    image = QImage.fromData(img_response.content)
                    pixmap = QPixmap.fromImage(image).scaled(200, 200, Qt.KeepAspectRatio)
                    self.ui.thumbnail_label.setPixmap(pixmap)
                else:
                    self.ui.thumbnail_label.setText("썸네일 로드 실패")
            else:
                self.ui.thumbnail_label.setText("썸네일 없음")

            logging.info(f"Loaded game data for {rj_code}: {data}")
        except Exception as e:
            self.ui.log_label.setText(f"데이터 로드 오류: {str(e)}")
            logging.error(f"Game data load error for {rj_code}: {str(e)}")
            self.ui.thumbnail_label.setText("오류")
            self.ui.title_label.setText("제목: N/A")
            self.ui.release_date_label.setText("출시일: N/A")
            self.ui.translated_label.setText("번역 상태: N/A")
            self.ui.tags_label.setPlainText("N/A")
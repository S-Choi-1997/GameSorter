from flask import Flask
from openai import OpenAI
from google.cloud import firestore
import requests
from bs4 import BeautifulSoup
import os
import time
import logging
from dotenv import load_dotenv

# .env 파일 로드 (로컬 환경용)
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.info("Starting app initialization...")

# 모듈 임포트 로깅
logger.info("Importing modules...")
try:
    logger.info("Imported flask")
    logger.info("Imported openai")
    logger.info("Imported google.cloud.firestore")
    logger.info("Imported requests")
    logger.info("Imported bs4")
    logger.info("Imported os, time")
    logger.info("Imported logging")
    logger.info("Imported dotenv")
except Exception as e:
    logger.error(f"Failed to import modules: {e}", exc_info=True)
    raise

app = Flask(__name__)

# OpenAI 초기화
logger.info("Initializing OpenAI client...")
client = None
try:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.warning("OPENAI_API_KEY is not set, translation functionality will be disabled")
    else:
        client = OpenAI(api_key=api_key)
        logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Unexpected error during OpenAI initialization: {e}", exc_info=True)

# Firestore 초기화
logger.info("Initializing Firestore client...")
db = None
try:
    db = firestore.Client()
    logger.info("Firestore client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Firestore client, database functionality will be disabled: {e}", exc_info=True)

# OpenAI 번역 함수
def translate_with_gpt(text, src_lang='ja', dest_lang='ko'):
    if not client:
        logger.warning("OpenAI client not available, skipping translation")
        return text
    if not text:
        return ''
    logger.info(f"Attempting to translate text: {text} from {src_lang} to {dest_lang}")
    try:
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',  # 안정적인 모델 사용
            messages=[
                {'role': 'system', 'content': f'Translate the following {src_lang} text to {dest_lang} accurately.'},
                {'role': 'user', 'content': text}
            ],
            max_tokens=100
        )
        translated_text = response.choices[0].message.content.strip()
        logger.info(f"Translation successful: {translated_text}")
        return translated_text
    except Exception as e:
        logger.error(f"GPT translation error: {str(e)}", exc_info=True)
        return text

# DLsite 스크래핑 함수
def fetch_from_dlsite(rj_code):
    url = f'https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        time.sleep(1)  # 요청 간 딜레이 추가
        logger.info(f"Fetching DLsite data for RJ code: {rj_code}")
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.select_one('#work_name')
        tags_elem = soup.select('div.main_genre a')
        date_elem = soup.select_one('th:contains("販売日") + td a')
        thumb_elem = soup.select_one('meta[property="og:image"]')
        rating_elem = soup.select_one('span[itemprop="ratingValue"]')

        if not title_elem:
            logger.error("Error: Title not found")
            return None

        title_jp = title_elem.text.strip()
        tags_jp = [tag.text.strip() for tag in tags_elem if tag.text.strip() and '[Error]' not in tag.text][:5]
        release_date = date_elem.text.strip() if date_elem else ''
        thumbnail_url = thumb_elem['content'] if thumb_elem else ''
        rating = float(rating_elem.text.strip()) if rating_elem else 0.0
        link = url

        data = {
            'title_jp': title_jp,
            'tags_jp': tags_jp,
            'release_date': release_date,
            'thumbnail_url': thumbnail_url,
            'rating': rating,
            'link': link
        }
        logger.info(f"Successfully fetched DLsite data for RJ code: {rj_code}")
        return data
    except Exception as e:
        logger.error(f"Error fetching DLsite: {e}", exc_info=True)
        return None

# 엔드포인트 정의
@app.route('/')
def hello():
    return "Hello, World!"

@app.route('/translate/<text>')
def translate(text):
    translated = translate_with_gpt(text)
    return {"original": text, "translated": translated}

@app.route('/save/<text>')
def save_text(text):
    if not db:
        logger.warning("Firestore client not available, skipping save operation")
        return {"error": "Database not available"}, 503
    translated = translate_with_gpt(text)
    try:
        doc_ref = db.collection('translations').document()
        doc_ref.set({
            'original': text,
            'translated': translated,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Saved translation to Firestore: original={text}, translated={translated}")
        return {"message": "Saved", "id": doc_ref.id}
    except Exception as e:
        logger.error(f"Error saving to Firestore: {e}", exc_info=True)
        return {"error": "Failed to save to Firestore"}, 500

@app.route('/dlsite/<rj_code>')
def get_dlsite(rj_code):
    data = fetch_from_dlsite(rj_code)
    if not data:
        logger.warning(f"No data found for RJ code: {rj_code}")
        return {"error": "Game not found"}, 404
    return data

logger.info("App initialization completed successfully")
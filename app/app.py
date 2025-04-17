from flask import Flask, request, jsonify
from google.cloud import firestore
import requests
from bs4 import BeautifulSoup
import os
import time
import logging
from dotenv import load_dotenv
from openai import OpenAI
import hashlib
import re

load_dotenv()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Firestore 초기화
db = None
try:
    db = firestore.Client()
    logger.info("Firestore client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Firestore: {e}", exc_info=True)

# 번역 함수
def translate_with_gpt(text, src_lang='ja', dest_lang='ko'):
    if not text:
        return ''
    try:
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': f'Translate the following {src_lang} text to {dest_lang} accurately.'},
                {'role': 'user', 'content': text}
            ],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT translation error: {e}")
        return text

# 고유 ID 생성
def generate_doc_id(title):
    return hashlib.md5(title.encode('utf-8')).hexdigest()

# DLsite 직접 스크래핑 함수
def fetch_from_dlsite_direct(rj_code):
    url = f'https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        time.sleep(1)
        logger.info(f"Fetching DLsite data for RJ code: {rj_code}")
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.select_one('#work_name')
        if not title_elem:
            logger.error("Error: Title not found")
            return None

        tags_elem = soup.select('div.main_genre a')
        date_elem = soup.select_one('th:contains("販売日") + td a')
        thumb_elem = soup.select_one('meta[property="og:image"]')
        rating_elem = soup.select_one('span[itemprop="ratingValue"]')

        data = {
            'rj_code': rj_code,
            'title_jp': title_elem.text.strip(),
            'tags_jp': [tag.text.strip() for tag in tags_elem if tag.text.strip() and '[Error]' not in tag.text][:5],
            'release_date': date_elem.text.strip() if date_elem else '',
            'thumbnail_url': thumb_elem['content'] if thumb_elem else '',
            'rating': float(rating_elem.text.strip()) if rating_elem else 0.0,
            'link': url,
            'platform': 'rj'
        }
        logger.info(f"Successfully fetched DLsite data for RJ code: {rj_code}")
        return data
    except Exception as e:
        logger.error(f"Error fetching DLsite: {e}", exc_info=True)
        return None

# DLsite 데이터 가져오기 (캐싱 포함)
def fetch_from_dlsite(rj_code):
    if not db:
        logger.warning("Firestore client not available, skipping cache")
        return fetch_from_dlsite_direct(rj_code)

    game_ref = db.collection('games').document('rj').collection('items').document(rj_code)
    game = game_ref.get()

    if game.exists:
        logger.info(f"Cache hit for RJ code {rj_code}")
        return game.to_dict()

    data = fetch_from_dlsite_direct(rj_code)
    if data:
        try:
            title_kr = translate_with_gpt(data['title_jp'])
            tags = [translate_with_gpt(tag) for tag in data['tags_jp']]
            data['title_kr'] = title_kr
            data['tags'] = tags
            game_ref.set(data)
            logger.info(f"Cached DLsite data for RJ code: {rj_code}")
        except Exception as e:
            logger.error(f"Error caching data: {e}", exc_info=True)
    return data

# Steam/기타 게임 데이터 조회
def fetch_from_firestore(title, platform):
    if not db:
        logger.warning("Firestore client not available")
        return None

    doc_id = generate_doc_id(title)
    game_ref = db.collection('games').document(platform).collection('items').document(doc_id)
    game = game_ref.get()

    if game.exists:
        logger.info(f"Cache hit for {platform} game: {title}")
        return game.to_dict()
    return None

# 여러 제목 처리 엔드포인트
@app.route('/games', methods=['POST'])
def get_games():
    data = request.get_json()
    if not data or 'items' not in data:
        logger.warning("Invalid request: items field required")
        return {"error": "Items field required"}, 400

    items = data['items']
    results = []

    for item in items:
        # RJ 코드 판별
        if re.match(r'^RJ\d{6,8}$', item, re.IGNORECASE):
            game_data = fetch_from_dlsite(item)
            if game_data:
                results.append(game_data)
            else:
                results.append({"rj_code": item, "platform": "rj", "error": "Game not found"})
        else:
            # Steam/기타 게임 처리 (기본적으로 steam으로 처리, other는 별도 조정 가능)
            game_data = fetch_from_firestore(item, 'steam')
            if game_data:
                results.append(game_data)
            else:
                game_data = fetch_from_firestore(item, 'other')
                if game_data:
                    results.append(game_data)
                else:
                    results.append({"title": item, "platform": "steam", "error": "Game not found"})

    logger.info(f"Processed {len(items)} items")
    return jsonify(results)

# 기존 단일 RJ 코드 엔드포인트 (호환성 유지)
@app.route('/dlsite/<rj_code>')
def get_dlsite(rj_code):
    data = fetch_from_dlsite(rj_code)
    if not data:
        logger.warning(f"No data found for RJ code: {rj_code}")
        return {"error": "Game not found"}, 404
    return data

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
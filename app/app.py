import json
import logging
import os
import time
from flask import Flask, request, jsonify
from google.cloud import firestore
from openai import OpenAI
import re

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Firestore 클라이언트 초기화
try:
    db = firestore.Client()
    logger.info("Firestore client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Firestore: {e}")
    db = None

# OpenAI 클라이언트 초기화
try:
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("OpenAI client initialized")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI: {e}")
    openai_client = None

# Firestore 캐시 확인
def get_cached_data(platform, identifier):
    if not db:
        return None
    try:
        doc_ref = db.collection('games').document(platform).collection('items').document(identifier)
        doc = doc_ref.get()
        if doc.exists:
            logger.debug(f"Cache hit for {platform}:{identifier}")
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Firestore cache error for {platform}:{identifier}: {e}")
        return None

def cache_data(platform, identifier, data):
    if not db:
        return
    try:
        doc_ref = db.collection('games').document(platform).collection('items').document(identifier)
        doc_ref.set(data)
        logger.info(f"Cached data for {platform}:{identifier}")
    except Exception as e:
        logger.error(f"Cache error for {platform}:{identifier}: {e}")

# 태그 캐시
def get_cached_tag(tag_jp):
    if not db:
        return None
    try:
        doc_ref = db.collection('tags').document('jp_to_kr').collection('mappings').document(tag_jp)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Tag cache error for {tag_jp}: {e}")
        return None

def cache_tag(tag_jp, tag_kr, priority):
    if not db:
        return
    try:
        doc_ref = db.collection('tags').document('jp_to_kr').collection('mappings').document(tag_jp)
        doc_ref.set({
            'tag_jp': tag_jp,
            'tag_kr': tag_kr,
            'priority': priority
        })
        logger.info(f"Cached tag: {tag_jp} -> {tag_kr}")
    except Exception as e:
        logger.error(f"Tag cache error for {tag_jp}: {e}")

# GPT 번역
def translate_with_gpt_batch(tags, batch_idx=""):
    if not openai_client:
        logger.warning("OpenAI client not initialized")
        return tags
    try:
        prompt = f"Translate the following Japanese tags to Korean naturally:\n{', '.join(tags)}\nProvide only the translated tags in a comma-separated list."
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a translator specializing in Japanese to Korean."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100
        )
        translated = response.choices[0].message.content.strip().split(',')
        return [t.strip() for t in translated][:len(tags)]
    except Exception as e:
        logger.error(f"GPT translation error for batch {batch_idx}: {e}")
        return tags

# RJ 데이터 처리
def process_rj_item(item):
    if 'error' in item:
        return item
    rj_code = item.get('rj_code')
    cached = get_cached_data('rj', rj_code)
    if cached:
        return cached

    tags_jp = item.get('tags_jp', [])
    tags_kr = []
    tags_to_translate = []
    tag_priorities = []

    for tag in tags_jp:
        cached_tag = get_cached_tag(tag)
        if cached_tag:
            tags_kr.append(cached_tag['tag_kr'])
            tag_priorities.append(cached_tag.get('priority', 10))
        else:
            tags_to_translate.append(tag)
            tag_priorities.append(10)

    if tags_to_translate:
        translated_tags = translate_with_gpt_batch(tags_to_translate, batch_idx=rj_code)
        for jp, kr in zip(tags_to_translate, translated_tags):
            priority = 10
            if kr in ["RPG", "액션", "판타지"]:
                priority = {"RPG": 100, "액션": 90, "판타지": 80}.get(kr, 10)
            tags_kr.append(kr)
            cache_tag(jp, kr, priority)
            tag_priorities[tags_kr.index(kr)] = priority

    primary_tag = tags_kr[tag_priorities.index(max(tag_priorities))] if tags_kr else "기타"

    processed_data = {
        'rj_code': rj_code,
        'title_jp': item.get('title_jp'),
        'title_kr': None,
        'primary_tag': primary_tag,
        'tags_jp': tags_jp,
        'tags': tags_kr,
        'release_date': item.get('release_date', 'N/A'),
        'thumbnail_url': item.get('thumbnail_url', ''),
        'rating': item.get('rating', 0.0),
        'link': item.get('link', ''),
        'platform': item.get('platform', 'rj'),
        'maker': item.get('maker', ''),
        'timestamp': time.time()
    }
    cache_data('rj', rj_code, processed_data)
    return processed_data

# Steam 데이터 처리
def process_steam_item(identifier):
    cached = get_cached_data('steam', identifier)
    if cached:
        return cached
    data = {
        'title': identifier,
        'primary_tag': "기타",
        'tags': ["기타"],
        'thumbnail_url': '',
        'platform': 'steam',
        'timestamp': time.time()
    }
    cache_data('steam', identifier, data)
    return data

# 게임 데이터 처리 엔드포인트
@app.route('/games', methods=['POST'])
def process_games():
    try:
        data = request.get_json()
        logger.info(f"Received request with data: {json.dumps(data, ensure_ascii=False)[:1000]}")
        items = data.get('items', [])
        logger.info(f"Processing {len(items)} items")

        results = []
        missing = []

        if not items:
            return jsonify({'results': [], 'missing': [], 'task_id': 'none'})

        # 문자열 배열 (캐시 확인) 또는 객체 배열 (크롤링 데이터) 처리
        if isinstance(items[0], str):
            for item in items:
                rj_match = re.match(r'^[Rr][Jj]\d{6,8}$', item, re.IGNORECASE)
                if rj_match:
                    rj_code = rj_match.group(0).upper()
                    cached = get_cached_data('rj', rj_code)
                    if cached:
                        results.append(cached)
                    else:
                        missing.append(rj_code)
                        results.append({'error': f'Game not found for {rj_code}', 'platform': 'rj', 'rj_code': rj_code})
                else:
                    results.append(process_steam_item(item))
        else:
            for item in items:
                rj_code = item.get('rj_code')
                if rj_code and re.match(r'^[Rr][Jj]\d{6,8}$', rj_code, re.IGNORECASE) and 'error' not in item:
                    results.append(process_rj_item(item))
                elif 'error' in item:
                    results.append(item)
                else:
                    results.append(process_steam_item(item.get('title', item)))

        task_id = request.headers.get('X-Cloud-Trace-Context', 'manual_task')[:36]
        logger.info(f"Returning response for task_id: {task_id}")
        return jsonify({'results': results, 'missing': missing, 'task_id': task_id})
    except Exception as e:
        logger.error(f"Error processing games: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# 진행 상황 엔드포인트
@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    try:
        logger.info(f"Progress request for task_id: {task_id}")
        return jsonify({'completed': 0, 'total': 1, 'status': 'completed'})
    except Exception as e:
        logger.error(f"Progress error for task {task_id}: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # GCP에서만 실행
    if os.getenv('GAE_ENV', '').startswith('standard') or os.getenv('CLOUD_RUN', '') == 'true':
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
    else:
        logger.warning("This script should only run in GCP environment. Exiting.")
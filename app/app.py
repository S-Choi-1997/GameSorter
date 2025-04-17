import json
import logging
import os
import time
import psutil
from flask import Flask, request, jsonify
from google.cloud import firestore
from openai import OpenAI
import re

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
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
    logger.info("Firestore client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Firestore client: {e}", exc_info=True)
    db = None

# OpenAI 클라이언트 초기화
try:
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
    openai_client = None

# 메모리 사용량 로깅
process = psutil.Process()
logger.info(f"Memory usage: RSS={process.memory_info().rss / 1024 / 1024:.2f}MB, "
            f"VMS={process.memory_info().vms / 1024 / 1024:.2f}MB")

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
        logger.debug(f"Cache miss for {platform}:{identifier}")
        return None
    except Exception as e:
        logger.error(f"Error accessing Firestore cache for {platform}:{identifier}: {e}", exc_info=True)
        return None

def cache_data(platform, identifier, data):
    if not db:
        return
    try:
        doc_ref = db.collection('games').document(platform).collection('items').document(identifier)
        doc_ref.set(data)
        logger.info(f"Cached data for {platform}:{identifier}")
    except Exception as e:
        logger.error(f"Error caching data for {platform}:{identifier}: {e}", exc_info=True)

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
        logger.error(f"Error accessing tag cache for {tag_jp}: {e}", exc_info=True)
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
        logger.error(f"Error caching tag {tag_jp}: {e}", exc_info=True)

# GPT 번역
def translate_with_gpt_batch(tags, batch_idx=""):
    if not openai_client:
        logger.warning("OpenAI client not initialized, skipping translation")
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
        logger.error(f"GPT translation error for batch {batch_idx}: {e}", exc_info=True)
        return tags

# RJ 데이터 가공
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

    if tags_kr:
        primary_tag_idx = tag_priorities.index(max(tag_priorities))
        primary_tag = tags_kr[primary_tag_idx]
    else:
        primary_tag = "기타"

    processed_data = {
        'rj_code': rj_code,
        'title_jp': item.get('title_jp'),
        'title_kr': None,
        'primary_tag': primary_tag,
        'tags_jp': tags_jp,
        'tags': tags_kr,
        'release_date': item.get('release_date', ''),
        'thumbnail_url': item.get('thumbnail_url', ''),
        'rating': item.get('rating', 0.0),
        'link': item.get('link', ''),
        'platform': 'rj',
        'maker': item.get('maker', ''),
        'timestamp': time.time()
    }
    cache_data('rj', rj_code, processed_data)
    return processed_data

# Steam 데이터 처리
def fetch_from_steam(identifier):
    cached = get_cached_data('steam', identifier)
    if cached:
        return cached
    logger.debug(f"No cache found for steam game: {identifier}")
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

# 엔드포인트
@app.route('/games', methods=['POST'])
def process_games():
    try:
        data = request.get_json()
        items = data.get('items', [])
        logger.info(f"Task {request.headers.get('X-Cloud-Trace-Context', 'unknown')}: Processing {len(items)} items")

        results = []
        missing = []

        # 문자열 배열 (초기 요청) 또는 객체 배열 (크롤링 데이터) 처리
        if items and isinstance(items[0], str):
            # 초기 요청: 캐시 확인
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
                    data = fetch_from_steam(item)
                    results.append(data)
        else:
            # 크롤링 데이터 처리
            for item in items:
                rj_match = re.match(r'^[Rr][Jj]\d{6,8}$', item.get('rj_code', ''), re.IGNORECASE)
                if rj_match and 'error' not in item:
                    processed = process_rj_item(item)
                    results.append(processed)
                elif 'error' in item:
                    results.append(item)
                else:
                    data = fetch_from_steam(item.get('title', item))
                    results.append(data)

        task_id = request.headers.get('X-Cloud-Trace-Context', 'manual_task')[:36]
        return jsonify({'results': results, 'missing': missing, 'task_id': task_id})
    except Exception as e:
        logger.error(f"Error processing games: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    try:
        return jsonify({'completed': 0, 'total': 1, 'status': 'completed'})
    except Exception as e:
        logger.error(f"Error fetching progress for task {task_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
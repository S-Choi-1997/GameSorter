import json
import logging
import os
import time
from urllib.parse import urljoin
import psutil
import requests
from flask import Flask, request, jsonify
from google.cloud import firestore
from bs4 import BeautifulSoup
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
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

# 프록시 설정
PROXY_URL = os.getenv("PROXY_URL")  # 예: http://user:pass@proxy-host:port
CUSTOM_COOKIES = os.getenv("DLSITE_COOKIES", "")  # 예: session=abc123;adultconfirmed=1

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

# DLsite 인증 페이지 처리
def handle_adult_check(session, url):
    try:
        logger.debug("Attempting to handle adult check")
        response = session.get(url, timeout=10)
        if 'adult_check' in response.text.lower() or 'age-verification' in response.url:
            logger.debug("Adult verification page detected")
            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.select_one('form[action*="adult_check"]')
            if not form:
                logger.error("Adult check form not found")
                return False
            action = urljoin(url, form.get('action', '/maniax/age-verification'))
            data = {input_tag.get('name'): input_tag.get('value', '') for input_tag in form.select('input')}
            data['adult_check'] = '1'  # 인증 확인
            response = session.post(action, data=data, timeout=10)
            logger.debug(f"Adult check POST response: {response.status_code}")
            if response.status_code == 200:
                return True
            logger.error(f"Adult check failed: Status {response.status_code}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error handling adult check: {e}", exc_info=True)
        return False

# DLsite 직접 스크래핑 (requests 기반)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda retry_state: logger.warning(
        f"Retrying DLsite request (attempt {retry_state.attempt_number}/3)"
    )
)
def fetch_from_dlsite_direct(rj_code):
    url = f'https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.dlsite.com/maniax/',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1'
    }
    cookies = {'adultconfirmed': '1'}
    if CUSTOM_COOKIES:
        try:
            for cookie in CUSTOM_COOKIES.split(';'):
                if cookie.strip():
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            logger.debug(f"Using custom cookies: {cookies}")
        except Exception as e:
            logger.warning(f"Invalid custom cookies format: {e}")

    proxies = {'https': PROXY_URL} if PROXY_URL else None
    try:
        logger.info(f"Fetching DLsite data for RJ code: {rj_code}")
        session = requests.Session()
        session.headers.update(headers)

        # 초기 요청으로 세션 쿠키 획득
        initial_response = session.get('https://www.dlsite.com/maniax/', timeout=10)
        logger.debug(f"Initial session response: {initial_response.status_code}")

        # 인증 페이지 처리
        if not handle_adult_check(session, url):
            logger.error(f"Failed to handle adult check for RJ code {rj_code}")
            return None

        # 메인 페이지 요청
        response = session.get(url, cookies=cookies, proxies=proxies, timeout=10)
        response.encoding = 'utf-8'
        logger.debug(f"DLsite response status: {response.status_code}, URL: {response.url}")
        logger.debug(f"Response content (first 500 chars): {response.text[:500]}")

        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code} for RJ code {rj_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        if 'age-verification' in response.url or 'adult_check' in response.text.lower():
            logger.warning(f"Adult verification page detected for RJ code {rj_code}")
            return None

        title_elem = soup.select_one('#work_name')
        if not title_elem:
            logger.error(f"Error: Title not found for RJ code {rj_code}")
            return None

        tags_elem = soup.select('div.main_genre a')
        date_elem = soup.select_one('th:-soup-contains("販売日") + td a')
        thumb_elem = soup.select_one('meta[property="og:image"]') or soup.select_one('img.work_thumb')
        rating_elem = soup.select_one('span[itemprop="ratingValue"]')
        maker_elem = soup.select_one('span.maker_name a')

        thumbnail_url = ''
        if thumb_elem:
            thumbnail_url = thumb_elem.get('content') or thumb_elem.get('src')
            if not thumbnail_url.startswith('http'):
                thumbnail_url = urljoin(url, thumbnail_url)
            logger.debug(f"Thumbnail URL found: {thumbnail_url}")

        tags_jp = [tag.text.strip() for tag in tags_elem if tag.text.strip() and '[Error]' not in tag.text][:5]
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

        data = {
            'rj_code': rj_code,
            'title_jp': title_elem.text.strip(),
            'title_kr': None,
            'primary_tag': primary_tag,
            'tags_jp': tags_jp,
            'tags': tags_kr,
            'release_date': date_elem.text.strip() if date_elem else '',
            'thumbnail_url': thumbnail_url,
            'rating': float(rating_elem.text.strip()) if rating_elem else 0.0,
            'link': url,
            'platform': 'rj',
            'maker': maker_elem.text.strip() if maker_elem else '',
            'timestamp': time.time()
        }
        cache_data('rj', rj_code, data)
        logger.info(f"Successfully fetched DLsite data for RJ code: {rj_code}")
        return data
    except Exception as e:
        logger.error(f"Error fetching DLsite for RJ code {rj_code}: {e}", exc_info=True)
        return None

# Steam 데이터 처리 (기존 유지)
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
        for item in items:
            rj_match = re.match(r'^[Rr][Jj]\d{6,8}$', item, re.IGNORECASE)
            if rj_match:
                rj_code = rj_match.group(0).upper()
                cached = get_cached_data('rj', rj_code)
                if cached:
                    results.append(cached)
                    continue
                data = fetch_from_dlsite_direct(rj_code)
                if data:
                    results.append(data)
                else:
                    results.append({'error': f'Game not found for {rj_code}', 'platform': 'rj', 'rj_code': rj_code})
            else:
                data = fetch_from_steam(item)
                results.append(data)

        task_id = request.headers.get('X-Cloud-Trace-Context', 'manual_task')[:36]
        return jsonify({'results': results, 'task_id': task_id})
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

@app.route('/dlsite/<rj_code>', methods=['GET'])
def get_dlsite_data(rj_code):
    try:
        rj_code = rj_code.upper()
        if not re.match(r'^RJ\d{6,8}$', rj_code):
            return jsonify({'error': 'Invalid RJ code format'}), 400
        data = fetch_from_dlsite_direct(rj_code)
        if data:
            return jsonify(data)
        return jsonify({'error': f'Game not found for {rj_code}'}), 404
    except Exception as e:
        logger.error(f"Error fetching DLsite data for {rj_code}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
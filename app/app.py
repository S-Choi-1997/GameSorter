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
import concurrent.futures
from queue import Queue
import uuid
try:
    import psutil
except ImportError:
    logging.warning("psutil not found, skipping memory usage logging")
    def log_memory_usage():
        logging.info("Memory usage logging skipped (psutil unavailable)")
else:
    def log_memory_usage():
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        logging.info(f"Memory usage: RSS={mem_info.rss / 1024 / 1024:.2f}MB, VMS={mem_info.vms / 1024 / 1024:.2f}MB")
import tenacity

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

# 진행 상황 저장
progress_data = {}

# 재시도 데코레이터
@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
    retry=tenacity.retry_if_exception_type((requests.exceptions.RequestException, Exception)),
    before_sleep=lambda retry_state: logger.warning(
        f"Retrying API call (attempt {retry_state.attempt_number}/3) after {retry_state.next_action.sleep} seconds"
    )
)
def make_openai_request(messages, max_tokens):
    return client.chat.completions.create(
        model='gpt-4o-mini',
        messages=messages,
        max_tokens=max_tokens
    )

# 태그 캐싱 조회 및 저장
def get_cached_tag(tag_jp):
    if not db:
        return None
    tag_ref = db.collection('tags').document(hashlib.md5(tag_jp.encode('utf-8')).hexdigest())
    tag_doc = tag_ref.get()
    if tag_doc.exists:
        logger.info(f"Cache hit for tag: {tag_jp}")
        return tag_doc.to_dict()
    return None

def cache_tag(tag_jp, tag_kr, priority=10):
    if not db:
        return
    tag_ref = db.collection('tags').document(hashlib.md5(tag_jp.encode('utf-8')).hexdigest())
    try:
        tag_ref.set({'tag_jp': tag_jp, 'tag_kr': tag_kr, 'priority': priority})
        logger.info(f"Cached tag: {tag_jp} -> {tag_kr} with priority {priority}")
    except Exception as e:
        logger.error(f"Error caching tag: {e}", exc_info=True)

# 번역 함수 (배치 처리)
def translate_with_gpt_batch(texts, src_lang='ja', dest_lang='ko', batch_idx=0):
    if not texts:
        return []
    try:
        prompt = (
            "다음 일본어 텍스트를 한국어로 번역하세요:\n"
            "- 직역 중심으로 번역하되, 자연스럽게 다듬어 원문 의미를 정확히 유지하세요.\n"
            "- 고유명사(예: 인물, 장소, 작품명)는 원문 그대로 유지하세요.\n"
            "- 특수문자(?, *, :, <, >, /, \\, |)는 제거하고, ?는 ,로 대체하세요.\n"
            "- 번역 요청한 내용 외의 표현은 절대 사용하지 마세요.\n"
            "- 출력은 번호 없이, 입력 순서대로 한 줄씩 번역된 텍스트만 반환하세요.\n"
            "입력:\n" + "\n".join(texts)
        )
        logger.info(f"Batch {batch_idx}: Sending translation request for {len(texts)} items")
        messages = [
            {'role': 'system', 'content': f'Translate the following {src_lang} text to {dest_lang} accurately and professionally.'},
            {'role': 'user', 'content': prompt}
        ]
        response = make_openai_request(messages, max_tokens=500)
        translated_texts = response.choices[0].message.content.strip().splitlines()
        if len(translated_texts) != len(texts):
            logger.error(f"Batch {batch_idx}: Translation response length mismatch: {len(translated_texts)} vs {len(texts)}")
            return [text for text in texts]
        logger.info(f"Batch {batch_idx}: Successfully translated {len(translated_texts)} items")
        return translated_texts
    except Exception as e:
        logger.error(f"Batch {batch_idx}: GPT translation error: {e}", exc_info=True)
        return [text for text in texts]

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
        maker_elem = soup.select_one('span.maker_name a')

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
            'thumbnail_url': thumb_elem['content'] if thumb_elem else '',
            'rating': float(rating_elem.text.strip()) if rating_elem else 0.0,
            'link': url,
            'platform': 'rj',
            'maker': maker_elem.text.strip() if maker_elem else '',
            'timestamp': time.time()
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
        cached_data = game.to_dict()
        cache_timestamp = cached_data.get('timestamp', 0)
        if time.time() - cache_timestamp < 7 * 24 * 3600:
            logger.info(f"Cache hit for RJ code {rj_code}")
            return cached_data

    data = fetch_from_dlsite_direct(rj_code)
    if data:
        try:
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
    try:
        log_memory_usage()
        data = request.get_json()
        if not data or 'items' not in data:
            logger.warning("Invalid request: items field required")
            return {"error": "Items field required"}, 400

        items = data['items']
        total_items = len(items)
        task_id = str(uuid.uuid4())
        progress_data[task_id] = {"total": total_items, "completed": 0, "status": "processing"}
        logger.info(f"Task {task_id}: Processing {total_items} items")

        batch_size = 10
        batches = [(i, items[i:i + batch_size]) for i in range(0, len(items), batch_size)]
        result_queue = Queue()

        def process_batch(batch_idx, batch_items):
            batch_results = []
            titles_to_translate = []
            items_to_update = []

            for item in batch_items:
                if re.match(r'^RJ\d{6,8}$', item, re.IGNORECASE):
                    rj_code = item.upper()
                    game_data = fetch_from_dlsite(rj_code)
                    if game_data:
                        if 'title_kr' not in game_data or not game_data['title_kr']:
                            titles_to_translate.append(game_data['title_jp'])
                            items_to_update.append((rj_code, game_data))
                        batch_results.append(game_data)
                    else:
                        batch_results.append({"rj_code": rj_code, "platform": "rj", "error": "Game not found"})
                else:
                    game_data = fetch_from_firestore(item, 'steam')
                    if game_data:
                        batch_results.append(game_data)
                    else:
                        game_data = fetch_from_firestore(item, 'other')
                        if game_data:
                            batch_results.append(game_data)
                        else:
                            batch_results.append({"title": item, "platform": "steam", "error": "Game not found"})

            if titles_to_translate:
                translated_titles = translate_with_gpt_batch(titles_to_translate, batch_idx=batch_idx)
                for (rj_code, game_data), translated_title in zip(items_to_update, translated_titles):
                    game_data['title_kr'] = translated_title
                    if db:
                        db.collection('games').document('rj').collection('items').document(rj_code).set(game_data)

            progress_data[task_id]["completed"] += len(batch_items)
            logger.info(f"Task {task_id}: Batch {batch_idx} completed, {progress_data[task_id]['completed']}/{total_items}")
            log_memory_usage()

            return batch_idx, batch_results

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(process_batch, i, batch_items)
                for i, batch_items in batches
            ]
            for future in concurrent.futures.as_completed(futures):
                batch_idx, batch_results = future.result()
                result_queue.put((batch_idx, batch_results))

        final_results = []
        while not result_queue.empty():
            batch_idx, batch_results = result_queue.get()
            final_results.append((batch_idx, batch_results))

        final_results.sort()
        response = []
        for _, batch_results in final_results:
            response.extend(batch_results)

        ordered_response = []
        for item in items:
            for res in response:
                if (res.get('rj_code', '').upper() == item.upper() or 
                    res.get('title', '').lower() == item.lower()):
                    ordered_response.append(res)
                    break

        progress_data[task_id]["status"] = "completed"
        logger.info(f"Task {task_id}: Processed {len(response)} items")
        log_memory_usage()
        return jsonify({"task_id": task_id, "results": ordered_response})
    except Exception as e:
        logger.error(f"Error in /games endpoint: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# 진행 상황 조회 엔드포인트
@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    if task_id not in progress_data:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(progress_data[task_id])

# 기존 단일 RJ 코드 엔드포인트
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
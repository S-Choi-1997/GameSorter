import json
import logging
import os
import time
import re
from flask import Flask, request, jsonify
from google.cloud import firestore
from google.cloud import storage
from openai import OpenAI

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
    logger.info("Firestore 클라이언트 초기화 완료")
except Exception as e:
    logger.error(f"Firestore 초기화 실패: {e}")
    db = None

# GCS 클라이언트 초기화
try:
    gcs_client = storage.Client()
    bucket_name = os.getenv("GCS_BUCKET_NAME", "rjcode")
    bucket = gcs_client.bucket(bucket_name)
    logger.info(f"GCS 클라이언트 초기화 완료, 버킷: {bucket_name}")
except Exception as e:
    logger.error(f"GCS 초기화 실패: {e}")
    gcs_client = None
    bucket = None

# OpenAI 클라이언트 초기화
try:
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("OpenAI 클라이언트 초기화 완료")
except Exception as e:
    logger.error(f"OpenAI 초기화 실패: {e}")
    openai_client = None

# 일본어 감지 함수
def needs_translation(title: str) -> bool:
    if not title or not isinstance(title, str):
        logger.debug(f"번역 불필요: 제목이 비어 있거나 유효하지 않음: {title}")
        return False
    # 히라가나(\u3040-\u309F), 가타카나(\u30A0-\u30FF), 한자(\u4E00-\u9FFF) 포함 여부 확인
    has_japanese = bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', title))
    logger.debug(f"일본어 감지 결과 '{title}': {'감지됨' if has_japanese else '감지되지 않음'}")
    return has_japanese

# GCS 경로 생성 함수
def get_gcs_path(platform, rj_code):
    # RJ 코드에서 숫자 부분만 추출 (예: RJ123456 -> 123456)
    number_part = rj_code[2:] if rj_code.startswith('RJ') else rj_code
    # 숫자 부분의 앞 두 글자 추출
    prefix = number_part[:2] if len(number_part) >= 2 else number_part.zfill(2)
    return f"{platform}/{prefix}/{rj_code}.json"

# GCS에서 캐시 불러오기
def get_cached_data(platform, identifier):
    if not bucket:
        logger.warning("GCS 버킷이 초기화되지 않음")
        return None
    rj_code = identifier.upper().replace('-', '').replace('_', '').strip()
    blob_path = get_gcs_path(platform, rj_code)
    blob = bucket.blob(blob_path)

    if blob.exists():
        content = blob.download_as_text()
        data = json.loads(content)

        # ✅ 404 혹은 오류 상태면 바로 리턴
        if data.get("status") == "404" or data.get("permanent_error"):
            logger.info(f"[GCS 캐시] 404 확인: {platform}:{rj_code}")
            return data

        # ✅ 타임스탬프 없는 경우 무효
        if not data.get("timestamp"):
            logger.warning(f"[GCS 캐시] 타임스탬프 없음: {platform}:{rj_code}")
            return None

        logger.info(f"[GCS 캐시] 조회 성공: {platform}:{rj_code}")
        return data
    return None

# GCS에 캐시 저장
def cache_data(platform, rj_code, data):
    if not bucket:
        logger.warning("GCS 버킷이 초기화되지 않음")
        return
    try:
        blob_path = get_gcs_path(platform, rj_code)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type='application/json')
        logger.info(f"[GCS 캐시] 저장 완료: {blob_path}")
    except Exception as e:
        logger.error(f"[GCS 캐시 오류] 저장 실패: {platform}/{rj_code}, 오류: {e}", exc_info=True)

# 태그 캐시
def get_cached_tag(tag_jp):
    if not db:
        return None
    try:
        safe_tag_id = normalize_tag_id(tag_jp)
        doc_ref = db.collection('tags').document('jp_to_kr').collection('mappings').document(safe_tag_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"태그 캐시 조회 오류: {tag_jp}: {e}")
        return None

def normalize_tag_id(tag_jp):
    # Firestore 문서 ID로 쓸 수 있도록 슬래시 제거 또는 대체
    return tag_jp.replace("/", "-")

def cache_tag(tag_jp, tag_kr, priority):
    if not db:
        return
    try:
        safe_tag_id = normalize_tag_id(tag_jp)
        normalized_tag_kr = normalize_tag_id(tag_kr)  # 🔥 하이픈 등으로 정제
        doc_ref = db.collection('tags').document('jp_to_kr').collection('mappings').document(safe_tag_id)
        doc_ref.set({
            'tag_jp': tag_jp,        # 원본 그대로 저장
            'tag_kr': normalized_tag_kr,
            'priority': priority
        })
        logger.info(f"태그 캐시 저장: {tag_jp} → {normalized_tag_kr} (ID: {safe_tag_id})")
    except Exception as e:
        logger.error(f"태그 캐시 저장 오류: {tag_jp}: {e}")

# GPT 번역
def translate_with_gpt_batch(tags, title_jp=None, batch_idx=""):
    if not openai_client:
        logger.warning("OpenAI 클라이언트가 초기화되지 않음")
        return tags, title_jp
    try:
        # 개선된 프롬프트
        prompt = (
            "당신은 일본어에서 한국어로 번역하는 전문 번역가입니다.\n"
            "아래의 태그들과 제목을 문맥에 맞게 한국어로 번역해주세요.\n"
            "반드시 JSON 형식으로만 응답하며, 예시와 동일한 구조를 따라야 합니다.\n"
            "제목(title)번역은 한국어나 영어인 경우만 생략해도 됩니다.\n\n"
            "출력 형식 예시:\n"
            "{\n"
            "  \"tags\": [\"번역된태그1\", \"번역된태그2\", ...],\n"
            "  \"title\": \"번역된제목\"\n"
            "}\n\n"
            "예시 입력/출력:\n"
            "Input:\n"
            "Tags: RPG, アクション\n"
            "Title: 少女の冒険\n"
            "Output:\n"
            "{\n"
            "  \"tags\": [\"RPG\", \"액션\"],\n"
            "  \"title\": \"소녀의 모험\"\n"
            "}\n\n"
            f"Input:\n"
            f"Tags: {', '.join(tags) if tags else '없음'}\n"
            f"Title: {title_jp if title_jp else '없음'}\n"
            "Output:"
        )

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a translator specializing in Japanese to Korean."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200
        )
        response_text = response.choices[0].message.content.strip()
        logger.debug(f"GPT 응답: {batch_idx}: {response_text}")

        # JSON 파싱
        try:
            response_json = json.loads(response_text)
            translated_tags = response_json.get('tags', tags)
            translated_title = response_json.get('title', title_jp) if title_jp else title_jp
        except json.JSONDecodeError:
            logger.warning(f"잘못된 JSON 응답: {batch_idx}: {response_text}")
            # 폴백: 기존 방식으로 파싱
            parts = response_text.split(';')
            translated_tags = [t.strip() for t in parts[0].split(',')][:len(tags)]
            translated_title = parts[1].strip() if len(parts) > 1 and title_jp else title_jp

        # 번역 실패 감지
        if title_jp and translated_title and needs_translation(translated_title):
            logger.warning(f"번역 실패: {batch_idx}: translated_title={translated_title}은 여전히 일본어")
            translated_title = title_jp  # 일본어로 반환된 경우 원본 유지

        logger.info(f"번역 완료: {batch_idx}: tags={translated_tags}, title={translated_title}")
        return translated_tags, translated_title
    except Exception as e:
        logger.error(f"GPT 번역 오류: 배치 {batch_idx}: {e}")
        return tags, title_jp  # 번역 실패 시 원래 제목 유지

# RJ 데이터 처리
def process_rj_item(item):
    if 'error' in item:
        rj_code = item.get('rj_code') or item.get('title') or item.get('original') or 'unknown'
        if not re.match(r'^RJ\d{6,8}$', rj_code, re.IGNORECASE):
            logger.warning(f"[오류 항목] 유효하지 않은 RJ 코드, 저장 생략: {rj_code}")
            return {
                'rj_code': rj_code,
                'error': item.get('error'),
                'platform': 'rj',
                'timestamp': time.time()
            }
        error_data = {
            'rj_code': rj_code,
            'platform': 'rj',
            'title': "알 수 없음",
            'title_kr': "알 수 없음",
            'title_jp': "不明",
            'tags': ["기타"],
            'tags_jp': ["その他"],
            'primary_tag': "기타",
            'error': item.get('error'),
            'timestamp': time.time()
        }
        logger.warning(f"[오류 항목] 캐시에 저장: {rj_code}")
        cache_data('rj', rj_code, error_data)
        return error_data

    rj_code = item.get('rj_code')
    cached = get_cached_data('rj', rj_code)
    if cached and cached.get('title_kr') and not needs_translation(cached.get('title_kr')):
        logger.debug(f"캐시 데이터 사용: {rj_code}: title_kr={cached.get('title_kr')}")
        return cached

    tags_jp = item.get('tags_jp', [])
    tags_jp = [tag.strip() for tag in tags_jp]  # 공백 제거
    tags_jp = [normalize_tag_id(tag) for tag in tags_jp]
    title_jp = item.get('title_jp', '')
    tags_kr = []
    tags_to_translate = []
    tag_priorities = []

    # RJ 코드 제거 함수
    def clean_title(title, rj_code):
        if not title or not rj_code:
            return title
        patterns = [
            rf"[\[\(]?\b{rj_code}\b[\]\)]?[)\s,;：]*",
            rf"[ _\-]?\bRJ\s*{rj_code[2:]}\b",
            rf"\b{rj_code}\b"
        ]
        cleaned = title
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    # title_jp 정제
    cleaned_title_jp = clean_title(title_jp, rj_code)

    for tag in tags_jp:
        cached_tag = get_cached_tag(tag)
        if cached_tag:
            kr = cached_tag['tag_kr']
            priority = cached_tag.get('priority', 10)
            tags_kr.append(kr)
            tag_priorities.append(priority)
        else:
            tags_to_translate.append(tag)
            tag_priorities.append(10)

    translated_tags = tags_jp
    translated_title = cleaned_title_jp

    if needs_translation(cleaned_title_jp) or tags_to_translate:
        logger.debug(f"번역 요청: {rj_code}: title_jp={cleaned_title_jp}, tags={tags_to_translate}")
        translated_tags, translated_title = translate_with_gpt_batch(
            tags_to_translate,
            cleaned_title_jp if needs_translation(cleaned_title_jp) else None,
            batch_idx=rj_code
        )
        # 번역된 제목도 RJ 코드 제거
        translated_title = clean_title(translated_title or cleaned_title_jp, rj_code)
        for i, (jp, kr) in enumerate(zip(tags_to_translate, translated_tags)):
            existing = get_cached_tag(jp)
            priority = existing.get("priority", 10) if existing else 10
            tags_kr.append(kr)
            tag_priorities.append(priority)
            cache_tag(jp, kr, priority)
    else:
        logger.debug(f"번역 불필요: {rj_code}: title_jp={cleaned_title_jp}")

    tag_with_priority = list(zip(tags_kr, tag_priorities))
    tag_with_priority.sort(key=lambda x: x[1], reverse=True)
    tags_kr_sorted = [tag for tag, _ in tag_with_priority]
    primary_tag = tags_kr_sorted[0] if tags_kr_sorted else "기타"

    processed_data = {
        'rj_code': rj_code,
        'title_jp': cleaned_title_jp,
        'title_kr': translated_title or cleaned_title_jp or rj_code,
        'primary_tag': primary_tag,
        'tags_jp': tags_jp,
        'tags': tags_kr_sorted,
        'release_date': item.get('release_date', 'N/A'),
        'thumbnail_url': item.get('thumbnail_url', ''),
        'rating': item.get('rating', 0.0),
        'link': item.get('link', ''),
        'platform': 'rj',
        'maker': item.get('maker', ''),
        'timestamp': time.time()
    }

    cache_data('rj', rj_code, processed_data)
    logger.info(f"RJ 항목 처리 완료: {rj_code}, title_kr={processed_data['title_kr']}")
    return processed_data

# Steam 데이터 처리
def process_steam_item(identifier):
    return {
        'title': identifier,
        'title_kr': identifier,
        'primary_tag': "기타",
        'tags': ["기타"],
        'thumbnail_url': '',
        'platform': '기타'  # 🔥 platform을 "steam" → "기타"로 변경
        # 'timestamp': time.time()
    }

# 게임 데이터 처리 엔드포인트
@app.route('/games', methods=['POST'])
def process_games():
    try:
        data = request.get_json()
        logger.info(f"요청 데이터 수신: {json.dumps(data, ensure_ascii=False)[:1000]}")
        items = data.get('items', [])
        logger.info(f"{len(items)}개 항목 처리 시작")

        results = []
        missing = []

        if not items:
            return jsonify({'results': [], 'missing': [], 'task_id': 'none'})

        for item in items:
            # 문자열(RJ 코드)만 받은 경우 딕셔너리로 변환
            if isinstance(item, str):
                # RJ 코드 패턴 확인
                if re.match(r'^RJ\d{6,8}$', item, re.IGNORECASE):
                    item = {
                        "rj_code": item.upper(),
                        "platform": "rj"
                    }
                    logger.info(f"[문자열 변환] {item['rj_code']}")
                else:
                    item = {
                        "title": item,
                        "platform": "steam"
                    }
                    logger.info(f"[문자열 변환] Steam 제목: {item['title']}")

            # 이제 item은 확실히 딕셔너리 타입
            logger.info(f"[항목 처리] {json.dumps(item, ensure_ascii=False)}")

            # 캐시 저장 요청일 경우 (크롤링 성공 or 실패 후)
            if isinstance(item, dict) and item.get("timestamp"):
                platform = item.get("platform", "rj")
                rj_code = item.get("rj_code")
                title = item.get("title_kr") or item.get("title") or rj_code

                # skip_translation 플래그 또는 404 상태이면 번역 없이 바로 처리
                if item.get("skip_translation") or item.get("status") == "404" or item.get("permanent_error"):
                    logger.info(f"[직접 저장] {platform}:{rj_code}")
                    processed = process_and_save_rj_item(item)  # 이미 번역 스킵 로직이 포함됨
                    results.append(processed)
                # 기존 번역/저장 조건
                elif platform == "rj" and (not item.get("title_kr") or not item.get("tags")):
                    logger.info(f"[번역 및 저장] {platform}:{rj_code}")
                    processed = process_and_save_rj_item(item)
                    results.append(processed)
                else:
                    cache_data(platform, rj_code, item)
                    logger.info(f"[저장 완료] {platform}/items/{rj_code}, title_kr={title}")
                    results.append(item)

            # 캐시 확인 요청일 경우
            else:
                rj_code = item.get("rj_code") if isinstance(item, dict) else None
                platform = item.get("platform", "rj") if isinstance(item, dict) else "rj"

                # RJ 없는 경우 steam 처리
                if not rj_code:
                    title = item.get("title", "untitled") if isinstance(item, dict) else str(item)
                    steam_fallback = process_steam_item(title)
                    logger.info(f"[Steam 모드] 제목={steam_fallback.get('title')}")
                    results.append(steam_fallback)
                    continue

                # 캐시 확인
                cached = get_cached_data(platform, rj_code)
                if cached and cached.get("timestamp"):
                    logger.info(f"[캐시 조회 성공] {platform}:{rj_code}")
                    results.append(cached)
                else:
                    logger.info(f"[캐시 조회 실패] {platform}:{rj_code}")
                    missing.append(rj_code)

        task_id = request.headers.get('X-Cloud-Trace-Context', 'manual_task')[:36]
        logger.info(f"응답 반환: task_id={task_id}, 결과={len(results)}, 누락={len(missing)}")
        return jsonify({'results': results, 'missing': missing, 'task_id': task_id})

    except Exception as e:
        logger.error(f"게임 처리 중 오류: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# 진행 상황 엔드포인트
@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    try:
        logger.info(f"진행 상황 요청: task_id={task_id}")
        return jsonify({'completed': 0, 'total': 1, 'status': 'completed'})
    except Exception as e:
        logger.error(f"진행 상황 조회 오류: task_id={task_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/sync-tags", methods=["POST"])
def sync_tags_to_games():
    try:
        logger.info("모든 게임의 태그 동기화 시작")

        # 1. 태그 변환 테이블 생성
        tag_map = {
            doc.id: doc.to_dict().get("tag_kr", doc.id)
            for doc in db.collection("tags").document("jp_to_kr").collection("mappings").stream()
        }
        tag_priority = {
            doc.id: doc.to_dict().get("priority", 10)
            for doc in db.collection("tags").document("jp_to_kr").collection("mappings").stream()
        }

        # 2. RJ 게임 문서들 업데이트
        games_ref = db.collection("games").document("rj").collection("items")
        updated_count = 0

        for doc in games_ref.stream():
            game = doc.to_dict()
            tags_jp = game.get("tags_jp", [])
            if not tags_jp:
                continue

            tags_kr = [tag_map.get(jp, "기타") for jp in tags_jp]
            primary_tag = max(tags_kr, key=lambda t: tag_priority.get(t, 0), default="기타")

            games_ref.document(doc.id).update({
                "tags": tags_kr,
                "primary_tag": primary_tag
            })
            updated_count += 1

        logger.info(f"태그 동기화 완료: {updated_count}개 문서 업데이트")
        return jsonify({"updated": updated_count})

    except Exception as e:
        logger.error(f"태그 동기화 오류: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/reorder-tags', methods=['POST'])
def reorder_tags():
    try:
        logger.info("태그 재정렬 작업 시작")

        # ✅ 태그 우선순위 로드
        tag_priority = {
            doc.id: doc.to_dict().get("priority", 10)
            for doc in db.collection("tags").document("jp_to_kr").collection("mappings").stream()
        }

        logger.info(f"{len(tag_priority)}개의 태그 우선순위 로딩 완료")

        # 🔄 전체 게임 순회
        games_ref = db.collection("games").document("rj").collection("items")
        updated = 0
        for doc in games_ref.stream():
            data = doc.to_dict()
            tags = data.get("tags", [])
            if not tags:
                continue

            original_tags = tags[:]
            # 🔽 우선순위 정렬
            sorted_tags = sorted(tags, key=lambda t: -tag_priority.get(t, 10))  # ✅ 높은 점수 우선
            primary_tag = sorted_tags[0] if sorted_tags else "기타"

            # ✅ 변경사항 있을 경우에만 업데이트
            if sorted_tags != tags or primary_tag != data.get("primary_tag"):
                doc.reference.update({
                    "tags": sorted_tags,
                    "primary_tag": primary_tag
                })
                logger.info(f"[업데이트] {doc.id}: {original_tags} → {sorted_tags}")
                updated += 1

        logger.info(f"태그 재정렬 완료: {updated}개 문서 업데이트")
        return jsonify({"status": "ok", "updated_documents": updated})
    except Exception as e:
        logger.error(f"태그 재정렬 오류: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def process_and_save_rj_item(item):
    """번역되지 않은 RJ 항목을 처리하고 저장"""
    rj_code = item.get("rj_code", "unknown")
    
    # 번역 스킵 플래그 확인
    if item.get("skip_translation") or item.get("status") == "404" or item.get("permanent_error"):
        logger.info(f"[번역 스킵] {rj_code}: 번역 없이 바로 저장")
        # title_kr이 없으면 original 또는 title 필드를 사용
        if not item.get("title_kr"):
            original_name = item.get("original") or item.get("title") or ""
            item["title_kr"] = clean_rj_code(original_name, rj_code)
        
        # 태그가 없으면 기본값 설정
        if not item.get("tags"):
            item["tags"] = ["기타"]
            item["primary_tag"] = "기타"
            
        cache_data("rj", rj_code, item)
        return item
    
    title_jp = item.get("title_jp", "")
    tags_jp = item.get("tags_jp", [])
    tags_jp = [normalize_tag_id(tag) for tag in tags_jp]

    if not title_jp and not tags_jp:
        logger.warning(f"[불완전 항목] {rj_code}: title_jp/tags_jp 없음")
        return item

    # title 정제
    def clean_title(title, rj_code):
        if not title or not rj_code:
            return title
        patterns = [
            rf"[\[\(]?\b{rj_code}\b[\]\)]?[)\s,;：]*",
            rf"[ _\-]?\bRJ\s*{rj_code[2:]}\b",
            rf"\b{rj_code}\b"
        ]
        for pattern in patterns:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
        return title

    cleaned_title = clean_title(title_jp, rj_code)

    # 태그 캐싱 확인 및 번역할 목록 추림
    tags_kr = []
    tags_to_translate = []
    priorities = []

    for tag in tags_jp:
        cached_tag = get_cached_tag(tag)
        if cached_tag:
            tags_kr.append(cached_tag['tag_kr'])
            priorities.append(cached_tag.get('priority', 10))
        else:
            tags_to_translate.append(tag)
            priorities.append(10)

    # 번역
    translated_tags, translated_title = translate_with_gpt_batch(
        tags_to_translate, cleaned_title if needs_translation(cleaned_title) else None, batch_idx=rj_code
    )

    # 캐싱
    for i, jp_tag in enumerate(tags_to_translate):
        kr_tag = translated_tags[i]
        cache_tag(jp_tag, kr_tag, priorities[i])
        tags_kr.append(kr_tag)

    # 우선순위 정렬
    tag_with_priority = list(zip(tags_kr, priorities))
    tag_with_priority.sort(key=lambda x: x[1], reverse=True)
    tags_kr_sorted = [tag for tag, _ in tag_with_priority]
    primary_tag = tags_kr_sorted[0] if tags_kr_sorted else "기타"

    # 최종 데이터 구성
    final = {
        **item,
        "title_kr": translated_title or cleaned_title or title_jp,
        "tags": tags_kr_sorted,
        "primary_tag": primary_tag,
        "timestamp": time.time()
    }

    # 저장
    cache_data("rj", rj_code, final)
    logger.info(f"[자동 저장] {rj_code} → {final['title_kr']}")
    return final

@app.route('/check_permanent_failure/<rj_code>', methods=['GET'])
def check_failure(rj_code):
    try:
        doc = db.collection("games").document("rj").collection("items").document(rj_code).get()
        if doc.exists:
            data = doc.to_dict()
            return jsonify({
                "permanent_failure": data.get("status") == "404" or data.get("permanent_error") == True
            })
        return jsonify({"permanent_failure": False})
    except Exception as e:
        logger.error(f"실패 확인 오류: {e}")
        return jsonify({"permanent_failure": False})

if __name__ == '__main__':
    # GCP에서만 실행
    if os.getenv('GAE_ENV', '').startswith('standard') or os.getenv('CLOUD_RUN', '') == 'true':
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
    else:
        logger.warning("이 스크립트는 GCP 환경에서만 실행해야 합니다. 종료합니다.")
import os
import re
import json
import logging
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("core.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()
PROXY_URL = os.getenv("PROXY_URL")
CUSTOM_COOKIES = os.getenv("DLSITE_COOKIES", "")
BACKEND_URL = os.getenv("BACKEND_URL", "https://gamesorter-28083845590.us-central1.run.app")

# DLsite 인증 페이지 처리
def handle_adult_check(session, url, headers):
    try:
        logger.debug(f"Attempting to handle adult check for URL: {url}")
        response = session.get(url, headers=headers, timeout=10)
        if 'adult_check' in response.text.lower() or 'age-verification' in response.url:
            logger.debug("Adult verification page detected")
            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.select_one('form[action*="/age-verification"], form[action*="/adult_check"]')
            if not form:
                logger.error("Adult check form not found")
                return False
            action = urljoin(url, form.get('action', '/maniax/age-verification'))
            data = {input_tag.get('name'): input_tag.get('value', '') for input_tag in form.select('input')}
            data['adult_check'] = '1'
            data['over_18'] = 'yes'
            logger.debug(f"Submitting adult check to {action} with data: {data}")
            response = session.post(action, data=data, headers=headers, timeout=10)
            logger.debug(f"Adult check POST response: {response.status_code}, Content: {response.text[:500]}")
            if response.status_code == 200 or response.status_code == 302:
                logger.debug("Adult check passed")
                return True
            logger.error(f"Adult check failed: Status {response.status_code}")
            return False
        logger.debug("No adult check required")
        return True
    except Exception as e:
        logger.error(f"Error handling adult check: {e}", exc_info=True)
        return False

# DLsite 크롤링
def fetch_from_dlsite(rj_code):
    url = f'https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
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
        initial_response = session.get('https://www.dlsite.com/maniax/', cookies=cookies, proxies=proxies, timeout=10)
        logger.debug(f"Initial session response: {initial_response.status_code}, Cookies: {session.cookies.get_dict()}")

        # 인증 페이지 처리
        if not handle_adult_check(session, url, headers):
            logger.error(f"Failed to handle adult check for RJ code {rj_code}")
            return None

        # 메인 페이지 요청
        response = session.get(url, cookies=cookies, proxies=proxies, timeout=10)
        response.encoding = 'utf-8'
        logger.debug(f"DLsite response status: {response.status_code}, URL: {response.url}")
        logger.debug(f"Response content (first 500 chars): {response.text[:500]}")

        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code} for RJ code {rj_code}")
            logger.debug(f"Full response content: {response.text}")
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

        data = {
            'rj_code': rj_code,
            'title_jp': title_elem.text.strip(),
            'title_kr': None,
            'tags_jp': [tag.text.strip() for tag in tags_elem if tag.text.strip() and '[Error]' not in tag.text][:5],
            'release_date': date_elem.text.strip() if date_elem else '',
            'thumbnail_url': thumbnail_url,
            'rating': float(rating_elem.text.strip()) if rating_elem else 0.0,
            'link': url,
            'platform': 'rj',
            'maker': maker_elem.text.strip() if maker_elem else '',
            'timestamp': time.time()
        }
        logger.info(f"Successfully fetched DLsite data for RJ code: {rj_code}")
        return data
    except Exception as e:
        logger.error(f"Error fetching DLsite for RJ code {rj_code}: {e}", exc_info=True)
        return None

# 백엔드에 데이터 전송
def send_to_backend(items):
    try:
        payload = {'items': items}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(f"{BACKEND_URL}/games", json=payload, headers=headers, timeout=10)
        logger.debug(f"Backend response status: {response.status_code}, Content: {response.text[:500]}")
        if response.status_code == 200:
            return response.json()
        logger.error(f"Backend request failed: Status {response.status_code}, {response.text}")
        return None
    except Exception as e:
        logger.error(f"Error sending data to backend: {e}", exc_info=True)
        return None

# 게임 데이터 처리
def process_games(folder_path):
    items = []
    rj_pattern = re.compile(r'[Rr][Jj]\d{6,8}')
    
    # 폴더에서 RJ 코드 추출
    for root, _, files in os.walk(folder_path):
        for file in files:
            match = rj_pattern.search(file)
            if match:
                items.append(match.group(0).upper())
    
    if not items:
        logger.warning("No RJ codes found in folder")
        return []

    # 백엔드에 초기 요청 (캐시 확인)
    logger.info(f"Sending {len(items)} items to backend for cache check")
    initial_response = send_to_backend(items)
    if not initial_response:
        logger.error("Failed to get response from backend")
        return []

    # 캐시된 결과 및 missing 코드 처리
    results = initial_response.get('results', [])
    missing = initial_response.get('missing', [])
    cached_results = [r for r in results if 'error' not in r]
    logger.info(f"Received {len(cached_results)} cached items, {len(missing)} missing RJ codes")

    # missing RJ 코드 크롤링
    crawled_data = []
    for rj_code in missing:
        data = fetch_from_dlsite(rj_code)
        if data:
            crawled_data.append(data)
        else:
            crawled_data.append({'error': f'Game not found for {rj_code}', 'platform': 'rj', 'rj_code': rj_code})

    # 로컬 JSON 저장
    try:
        with open('crawled_data.json', 'w', encoding='utf-8') as f:
            json.dump(crawled_data, f, ensure_ascii=False, indent=2)
        logger.info("Crawled data saved to crawled_data.json")
    except Exception as e:
        logger.error(f"Error saving crawled data: {e}", exc_info=True)

    # 크롤링 데이터 백엔드로 전송
    if crawled_data:
        logger.info(f"Sending {len(crawled_data)} crawled items to backend")
        final_response = send_to_backend(crawled_data)
        if final_response:
            crawled_results = final_response.get('results', [])
            logger.info(f"Received {len(crawled_results)} processed items from backend")
            return cached_results + crawled_results
        else:
            logger.warning("Failed to process crawled data in backend")
            return cached_results + crawled_data

    return cached_results

if __name__ == "__main__":
    folder_path = "H:/yangame/방주"
    results = process_games(folder_path)
    for result in results:
        logger.info(f"Processed: {result.get('rj_code', result.get('error'))}")
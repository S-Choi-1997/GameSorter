import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import logging
import time
import re
from urllib.parse import urljoin
import argparse

# 로그 설정
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("test_crawling.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 데이터 파싱 공통 함수
def parse_game_data(soup, rj_code, url):
    try:
        title_elem = soup.select_one('#work_name')
        if not title_elem:
            logger.error(f"No title found for RJ code {rj_code}")
            return None

        tags_elem = soup.select('div.main_genre a')
        date_elem = soup.select_one('th:contains("販売日") + td a')
        thumb_elem = soup.select_one('meta[property="og:image"]') or soup.select_one('img.work_thumb')
        maker_elem = soup.select_one('span.maker_name a')

        thumbnail_url = ''
        if thumb_elem:
            thumbnail_url = thumb_elem.get('content') or thumb_elem.get('src')
            if thumbnail_url and not thumbnail_url.startswith('http'):
                thumbnail_url = urljoin(url, thumbnail_url)
            logger.debug(f"Thumbnail URL: {thumbnail_url}")

        data = {
            'rj_code': rj_code,
            'title': title_elem.text.strip(),
            'tags': [tag.text.strip() for tag in tags_elem if tag.text.strip()][:5],
            'release_date': date_elem.text.strip() if date_elem else 'N/A',
            'thumbnail_url': thumbnail_url,
            'maker': maker_elem.text.strip() if maker_elem else 'N/A',
            'link': url
        }
        logger.info(f"Parsed data for RJ code {rj_code}: {data}")
        return data
    except Exception as e:
        logger.error(f"Error parsing data for RJ code {rj_code}: {e}", exc_info=True)
        return None

# 방식 1: 기본 requests
def crawl_with_requests(rj_code):
    url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.dlsite.com/maniax/',
        'DNT': '1',
        'Connection': 'keep-alive'
    }
    try:
        logger.info(f"Attempting requests crawl for RJ code {rj_code}")
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        logger.debug(f"Response status: {response.status_code}, URL: {response.url}")

        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code} for RJ code {rj_code}")
            return {"error": f"HTTP {response.status_code}"}

        soup = BeautifulSoup(response.text, 'html.parser')
        if 'age-verification' in response.url or 'adult_check' in response.text.lower():
            logger.warning(f"Adult verification page detected for RJ code {rj_code}")
            return {"error": "Adult verification required"}

        data = parse_game_data(soup, rj_code, url)
        if data:
            return data
        return {"error": "Failed to parse data"}
    except Exception as e:
        logger.error(f"Requests crawl error for RJ code {rj_code}: {e}", exc_info=True)
        return {"error": str(e)}

# 방식 2: 쿠키 포함 requests
def crawl_with_requests_cookies(rj_code, custom_cookies=""):
    url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.dlsite.com/maniax/',
        'DNT': '1',
        'Connection': 'keep-alive'
    }
    cookies = {'adultconfirmed': '1'}
    if custom_cookies:
        try:
            for cookie in custom_cookies.split(';'):
                if cookie.strip():
                    key, value = cookie.strip().split('=', 1)
                    cookies[key] = value
            logger.debug(f"Using custom cookies: {cookies}")
        except Exception as e:
            logger.warning(f"Invalid custom cookies format: {e}")

    try:
        logger.info(f"Attempting requests with cookies crawl for RJ code {rj_code}")
        session = requests.Session()
        response = session.get(url, headers=headers, cookies=cookies, timeout=10)
        response.encoding = 'utf-8'
        logger.debug(f"Response status: {response.status_code}, URL: {response.url}")

        if response.status_code != 200:
            logger.error(f"HTTP Error: Status code {response.status_code} for RJ code {rj_code}")
            return {"error": f"HTTP {response.status_code}"}

        soup = BeautifulSoup(response.text, 'html.parser')
        if 'age-verification' in response.url or 'adult_check' in response.text.lower():
            logger.warning(f"Adult verification page detected for RJ code {rj_code}")
            return {"error": "Adult verification required"}

        data = parse_game_data(soup, rj_code, url)
        if data:
            return data
        return {"error": "Failed to parse data"}
    except Exception as e:
        logger.error(f"Requests with cookies crawl error for RJ code {rj_code}: {e}", exc_info=True)
        return {"error": str(e)}

# 방식 3: Playwright
def crawl_with_playwright(rj_code):
    url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
    try:
        logger.info(f"Attempting playwright crawl for RJ code {rj_code}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.goto(url, timeout=30000)

            # 성인 인증 처리
            if 'age-verification' in page.url or 'adult_check' in page.url:
                logger.debug(f"Adult verification detected for RJ code {rj_code}")
                try:
                    page.click('button:has-text("はい、18歳以上です")', timeout=10000)
                    page.wait_for_load_state('load', timeout=20000)
                    logger.debug(f"Adult verification passed for RJ code {rj_code}")
                except Exception as e:
                    logger.warning(f"Failed to handle adult verification for RJ code {rj_code}: {e}")
                    browser.close()
                    return {"error": f"Adult verification failed: {str(e)}"}

            # 404 확인
            if page.url.endswith('404.html') or page.title().lower().startswith('not found'):
                logger.error(f"Page not found for RJ code {rj_code}, URL: {page.url}")
                browser.close()
                return {"error": "HTTP 404"}

            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            data = parse_game_data(soup, rj_code, url)
            browser.close()
            if data:
                return data
            return {"error": "Failed to parse data"}
    except Exception as e:
        logger.error(f"Playwright crawl error for RJ code {rj_code}: {e}", exc_info=True)
        return {"error": str(e)}

# 결과 출력 함수
def print_results(method, result):
    print(f"\n=== {method} ===")
    if "error" in result:
        print(f"실패: {result['error']}")
    else:
        print("성공!")
        print(f"제목: {result.get('title', 'N/A')}")
        print(f"썸네일 URL: {result.get('thumbnail_url', 'N/A')}")
        print(f"태그: {', '.join(result.get('tags', []))}")
        print(f"제작자: {result.get('maker', 'N/A')}")
        print(f"출시일: {result.get('release_date', 'N/A')}")
        print(f"링크: {result.get('link', 'N/A')}")
    print("================\n")

# 메인 테스트 함수
def test_crawling_methods(rj_code, custom_cookies=""):
    logger.info(f"Starting crawling test for RJ code: {rj_code}")
    results = {}

    # 방식 1: 기본 requests
    start_time = time.time()
    results['requests'] = crawl_with_requests(rj_code)
    logger.info(f"Basic requests took {time.time() - start_time:.2f} seconds")
    print_results("기본 requests", results['requests'])

    # 방식 2: 쿠키 포함 requests
    start_time = time.time()
    results['requests_cookies'] = crawl_with_requests_cookies(rj_code, custom_cookies)
    logger.info(f"Requests with cookies took {time.time() - start_time:.2f} seconds")
    print_results("쿠키 포함 requests", results['requests_cookies'])

    # 방식 3: Playwright
    start_time = time.time()
    results['playwright'] = crawl_with_playwright(rj_code)
    logger.info(f"Playwright took {time.time() - start_time:.2f} seconds")
    print_results("Playwright", results['playwright'])

    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test different crawling methods for DLsite RJ code")
    parser.add_argument("rj_code", help="RJ code to test (e.g., RJ01173055)")
    parser.add_argument("--cookies", default="", help="Custom cookies for requests (e.g., 'key1=value1;key2=value2')")
    args = parser.parse_args()

    # RJ 코드 유효성 검사
    rj_code = args.rj_code.upper()
    if not re.match(r'^RJ\d{6,8}$', rj_code):
        logger.error(f"Invalid RJ code format: {rj_code}")
        print("오류: RJ 코드 형식이 잘못되었습니다. (예: RJ01173055)")
        exit(1)

    # 테스트 실행
    results = test_crawling_methods(rj_code, args.cookies)
    logger.info(f"Test completed for RJ code: {rj_code}")
    print("테스트 완료! 자세한 로그는 test_crawling.log를 확인하세요.")
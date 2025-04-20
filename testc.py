import requests
import re
from bs4 import BeautifulSoup

def test_dlsite_tags(rj_code):
    """
    DLsite 태그 파싱 테스트 - 다양한 태그 선택자를 테스트합니다
    """
    print(f"===== DLsite 태그 선택자 테스트: {rj_code} =====\n")
    
    url = f"https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        'Accept-Language': 'ja',
        'Referer': 'https://www.dlsite.com/maniax/'
    }
    cookies = {'adultconfirmed': '1'}
    
    try:
        print(f"요청 URL: {url}")
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            print(f"❌ 오류: 상태 코드 {response.status_code}")
            return
            
        if 'age-verification' in response.url or 'adult_check' in response.text.lower():
            print("❌ 오류: 성인 인증 페이지 감지됨")
            return
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 제목 출력 (참고용)
        title_elem = soup.select_one('#work_name')
        print(f"제목: {title_elem.text.strip() if title_elem else '없음'}\n")
        
        # 여러 태그 선택자 테스트
        tag_selectors = [
            'div.main_genre a',
            'div.work_genre a',
            '.genre a',
            '.genreTag a',
            '#work_outline a',
            '.work_right_info a',
            '.work_right_info .main_genre a',
            '.main_genre a',
            '.search_tag a',
            'th:contains("ジャンル") + td a',
            '.work_parts_container a',
            '.work_genre_tag a',
            '#work_outline .main_genre a',
            '.work_genre .search_tag'
        ]
        
        print("===== 각 선택자별 태그 결과 =====")
        for selector in tag_selectors:
            print(f"\n>> 선택자: '{selector}'")
            try:
                if ':contains' in selector:
                    # BeautifulSoup에서 contains 선택자 처리
                    text = selector.split(':contains("')[1].split('")')[0]
                    th_elem = soup.find('th', string=re.compile(r'' + text))
                    if th_elem:
                        td_elem = th_elem.find_next_sibling('td')
                        if td_elem:
                            tags = td_elem.select('a')
                            if tags:
                                for i, tag in enumerate(tags, 1):
                                    print(f"  {i}. {tag.text.strip()}")
                            else:
                                print("  (결과 없음)")
                        else:
                            print("  (td 요소 없음)")
                    else:
                        print("  (th 요소 없음)")
                else:
                    # 일반 CSS 선택자
                    tags = soup.select(selector)
                    if tags:
                        for i, tag in enumerate(tags, 1):
                            print(f"  {i}. {tag.text.strip()}")
                    else:
                        print("  (결과 없음)")
            except Exception as e:
                print(f"  (선택자 오류: {e})")
        
        # HTML 구조 분석 (일부 확인용)
        print("\n===== 일반적인 태그 구조 분석 =====")
        
        # 1. 'ジャンル' 테이블 확인
        print("\n>> 'ジャンル' 테이블 확인:")
        tables = soup.select('table')
        for i, table in enumerate(tables):
            genre_th = table.find('th', string=re.compile(r'ジャンル'))
            if genre_th:
                print(f"  테이블 {i+1}에서 ジャンル 발견:")
                print(f"  - th 텍스트: {genre_th.text.strip()}")
                td = genre_th.find_next_sibling('td')
                if td:
                    links = td.select('a')
                    for j, link in enumerate(links, 1):
                        print(f"    {j}. {link.text.strip()}")
                else:
                    print("    (td 없음)")
        
        # 2. main_genre 구조 확인
        print("\n>> 'main_genre' 클래스 구조:")
        main_genres = soup.select('.main_genre')
        for i, mg in enumerate(main_genres, 1):
            print(f"  main_genre {i}:")
            links = mg.select('a')
            if links:
                for j, link in enumerate(links, 1):
                    print(f"    {j}. {link.text.strip()}")
            else:
                print("    (링크 없음)")
            
        # 3. work_genre 구조 확인
        print("\n>> 'work_genre' 클래스 구조:")
        work_genres = soup.select('.work_genre')
        for i, wg in enumerate(work_genres, 1):
            print(f"  work_genre {i}:")
            links = wg.select('a')
            if links:
                for j, link in enumerate(links, 1):
                    print(f"    {j}. {link.text.strip()}")
            else:
                print("    (링크 없음)")
                
    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    while True:
        rj_input = input("\nRJ 코드를 입력하세요 (종료하려면 q): ")
        if rj_input.lower() == 'q':
            break
            
        # RJ 코드 정규화
        if rj_input.lower().startswith('rj'):
            rj_code = rj_input.upper()
        else:
            rj_code = f"RJ{rj_input}"
            
        test_dlsite_tags(rj_code)
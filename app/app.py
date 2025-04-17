from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from google.cloud import firestore
import os
import time
import hashlib

app = Flask(__name__)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
db = firestore.Client()

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
        print(f"GPT translation error: {e}")
        return text

def generate_doc_id(title):
    return hashlib.md5(title.encode('utf-8')).hexdigest()

@app.route('/rj/<rj_code>', methods=['GET'])
def get_game_by_rj_code(rj_code):
    game_ref = db.collection('games').document('rj').collection('items').document(rj_code)
    game = game_ref.get()

    if game.exists:
        return jsonify(game.to_dict())

    game_data = fetch_from_dlsite(rj_code)
    if not game_data:
        return jsonify({'error': 'Game not found'}), 404

    title_kr = translate_with_gpt(game_data['title_jp'])
    tags_kr = [translate_with_gpt(tag) for tag in game_data['tags_jp']]

    game_data['title_kr'] = title_kr
    game_data['tags'] = tags_kr
    game_data['translated'] = bool(title_kr != game_data['title_jp'])

    game_ref.set(game_data)
    return jsonify(game_data)

@app.route('/game', methods=['GET'])
def get_game_by_name():
    title = request.args.get('title')
    platform = request.args.get('platform', 'rj')  # 기본값은 rj
    if not title:
        return jsonify({'error': 'Title parameter is required'}), 400

    if platform not in ['rj', 'steam', 'other']:
        return jsonify({'error': 'Invalid platform. Use rj, steam, or other'}), 400

    if platform == 'rj':
        # RJ 게임은 제목이 아닌 RJ 코드로 조회해야 하므로 별도 처리
        return jsonify({'error': 'Use /rj/<rj_code> for RJ games'}), 400

    # Steam/기타 게임은 제목 기반 고유 ID로 조회
    doc_id = generate_doc_id(title)
    game_ref = db.collection('games').document(platform).collection('items').document(doc_id)
    game = game_ref.get()

    if game.exists:
        return jsonify(game.to_dict())

    return jsonify({'error': 'Game not found'}), 404

@app.route('/game', methods=['POST'])
def add_game():
    data = request.get_json()
    if not data or 'title_jp' not in data or 'platform' not in data:
        return jsonify({'error': 'title_jp and platform are required'}), 400

    platform = data['platform']
    if platform not in ['rj', 'steam', 'other']:
        return jsonify({'error': 'Invalid platform. Use rj, steam, or other'}), 400

    # RJ 게임은 별도 엔드포인트 사용
    if platform == 'rj':
        return jsonify({'error': 'Use /rj/<rj_code> for RJ games'}), 400

    # 필수 필드 설정 및 기본값 제공
    title_jp = data.get('title_jp')
    title_kr = data.get('title_kr', translate_with_gpt(title_jp))
    tags_jp = data.get('tags_jp', [])
    tags = [translate_with_gpt(tag) for tag in tags_jp] if tags_jp else data.get('tags', [])
    game_data = {
        'title_jp': title_jp,
        'title_kr': title_kr,
        'tags_jp': tags_jp,
        'tags': tags,
        'rating': data.get('rating', 0.0),
        'thumbnail_url': data.get('thumbnail_url', ''),
        'release_date': data.get('release_date', ''),
        'link': data.get('link', ''),  # dlsite_link 대신 platform별 link로 통일
        'translated': bool(title_kr != title_jp)
    }

    # Steam/기타 게임은 제목 기반 고유 ID 사용
    doc_id = generate_doc_id(title_jp)
    game_ref = db.collection('games').document(platform).collection('items').document(doc_id)
    game_ref.set(game_data)
    return jsonify({'message': 'Game added', 'doc_id': doc_id}), 201

def fetch_from_dlsite(rj_code):
    url = f'https://www.dlsite.com/maniax/work/=/product_id/{rj_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        time.sleep(1)
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            print(f"HTTP Error: Status code {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.select_one('#work_name')
        tags_elem = soup.select('div.main_genre a')
        date_elem = soup.select_one('th:contains("販売日") + td a')
        thumb_elem = soup.select_one('meta[property="og:image"]')
        rating_elem = soup.select_one('span[itemprop="ratingValue"]')

        if not title_elem:
            print("Error: Title not found")
            return None

        title_jp = title_elem.text.strip()
        tags_jp = [tag.text.strip() for tag in tags_elem if tag.text.strip() and '[Error]' not in tag.text][:5]
        release_date = date_elem.text.strip() if date_elem else ''
        thumbnail_url = thumb_elem['content'] if thumb_elem else ''
        rating = float(rating_elem.text.strip()) if rating_elem else 0.0
        link = url

        return {
            'title_jp': title_jp,
            'tags_jp': tags_jp,
            'release_date': release_date,
            'thumbnail_url': thumbnail_url,
            'rating': rating,
            'link': link
        }
    except Exception as e:
        print(f"Error fetching DLsite: {e}")
        return None

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
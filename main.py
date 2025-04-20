from flask import Flask, send_from_directory
from flask_cors import CORS
from google.cloud import firestore
import logging
import os
from tags import tag_bp, init_tags
from games import game_bp
from game2 import game_fs_bp  

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 프로덕션에서는 제한 필요: CORS(app, resources={r"/*": {"origins": "https://your-frontend.com"}})

# Firestore 클라이언트 초기화
db = firestore.Client()

# tags.py 초기화
init_tags(db)

# Blueprint 등록
app.register_blueprint(tag_bp, url_prefix="/tags")
app.register_blueprint(game_bp, url_prefix="/games")
app.register_blueprint(game_fs_bp, url_prefix="/games-fs")

# 웹 라우팅
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
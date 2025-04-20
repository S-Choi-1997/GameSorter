from flask import Blueprint, request, jsonify
from google.cloud import storage
import json, logging

game_bp = Blueprint("games", __name__)
logger = logging.getLogger(__name__)

BUCKET_NAME = "rjcode"
gcs_client = storage.Client()
bucket = gcs_client.bucket(BUCKET_NAME)

def get_gcs_path(platform, rj_code):
    number_part = rj_code[2:] if rj_code.upper().startswith('RJ') else rj_code
    prefix = number_part[:2] if len(number_part) >= 2 else number_part.zfill(2)
    return f"{platform}/{prefix}/{rj_code}.json"

@game_bp.route("/<platform>/<rj_code>", methods=["GET"])
def get_game(platform, rj_code):
    path = get_gcs_path(platform, rj_code)
    blob = bucket.blob(path)

    if not blob.exists():
        return jsonify({"error": "Not found"}), 404

    try:
        content = blob.download_as_text()
        return jsonify(json.loads(content))
    except Exception as e:
        logger.error(f"[GET] Failed to read {path}: {e}")
        return jsonify({"error": str(e)}), 500

@game_bp.route("/<platform>/<rj_code>", methods=["POST"])
def update_game(platform, rj_code):
    path = get_gcs_path(platform, rj_code)
    blob = bucket.blob(path)

    try:
        data = request.get_json()
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"[POST] Failed to write {path}: {e}")
        return jsonify({"error": str(e)}), 500
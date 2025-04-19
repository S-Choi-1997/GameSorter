from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google.cloud import firestore
import logging
import os

app = Flask(__name__)
CORS(app)
db = firestore.Client()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TAGS_COLLECTION = db.collection('tags').document('jp_to_kr').collection('mappings')
PIN_DOC = db.collection('settings').document('pin')


@app.route("/")
def serve_index():
    return send_from_directory("static", "index.html")


@app.route("/tags", methods=["GET"])
def get_tags():
    tags = TAGS_COLLECTION.stream()
    result = []
    for doc in tags:
        data = doc.to_dict()
        result.append({
            "tag_jp": data.get("tag_jp"),
            "tag_kr": data.get("tag_kr"),
            "priority": data.get("priority", 10)
        })
    return jsonify(sorted(result, key=lambda x: x['priority'], reverse=True))


@app.route("/tags", methods=["POST"])
def save_tag():
    data = request.get_json()
    tag_jp = data.get("tag_jp")
    tag_kr = data.get("tag_kr")
    priority = int(data.get("priority", 10))

    if not tag_jp or not tag_kr:
        return jsonify({"error": "tag_jp and tag_kr required"}), 400

    TAGS_COLLECTION.document(tag_jp).set({
        "tag_jp": tag_jp,
        "tag_kr": tag_kr,
        "priority": priority
    })

    logger.info(f"Saved tag: {tag_jp} -> {tag_kr} ({priority})")
    return jsonify({"success": True})


# 🔐 PIN 확인 API
@app.route("/auth", methods=["POST"])
def verify_pin():
    data = request.get_json()
    user_pin = data.get("pin")

    if not user_pin:
        return jsonify({"error": "Missing pin"}), 400

    doc = PIN_DOC.get()
    if not doc.exists:
        return jsonify({"error": "No PIN set"}), 404

    saved_pin = doc.to_dict().get("pin")
    if user_pin == saved_pin:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False})


# 🔧 PIN 설정 API (검증 없이 그냥 바꿈)
@app.route("/auth/set", methods=["POST"])
def set_pin():
    data = request.get_json()
    new_pin = data.get("pin")

    if not new_pin or not new_pin.isdigit() or len(new_pin) != 4:
        return jsonify({"error": "PIN must be 4-digit number"}), 400

    PIN_DOC.set({"pin": new_pin})
    logger.info(f"PIN updated to: {new_pin}")
    return jsonify({"success": True})

@app.route("/sync-tags", methods=["POST"])
def sync_tags_to_games():
    try:
        logger.info("Syncing tags to all game documents...")

        tag_map = {
            doc.id: doc.to_dict().get("tag_kr", doc.id)
            for doc in TAGS_COLLECTION.stream()
        }
        tag_priority = {
            doc.id: doc.to_dict().get("priority", 10)
            for doc in TAGS_COLLECTION.stream()
        }

        game_items = db.collection('games').document('rj').collection('items').stream()
        updated = 0

        for doc in game_items:
            data = doc.to_dict()
            tags_jp = data.get("tags_jp", [])
            if not tags_jp:
                continue

            # tag_jp -> (tag_kr, priority) 형태로 변환
            tags_with_priority = [
                (tag_map.get(jp, "기타"), tag_priority.get(jp, 10))
                for jp in tags_jp
            ]

            # priority 내림차순 정렬
            tags_with_priority.sort(key=lambda x: x[1], reverse=True)

            # 정렬된 태그 이름 리스트
            tags_kr = [tag for tag, _ in tags_with_priority]

            # 가장 높은 우선순위의 태그를 primary_tag로 선택
            best_tag = tags_kr[0] if tags_kr else "기타"

            doc_ref = db.collection('games').document('rj').collection('items').document(doc.id)
            doc_ref.update({
                "tags": tags_kr,
                "primary_tag": best_tag
            })
            updated += 1

        logger.info(f"Tags synced to {updated} games.")
        return jsonify({"updated": updated})

    except Exception as e:
        logger.error(f"Error in /sync-tags: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

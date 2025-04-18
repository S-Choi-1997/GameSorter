from flask import Flask, request, jsonify
from google.cloud import firestore
from flask_cors import CORS
import logging

app = Flask(__name__)
CORS(app)  # 모든 origin 허용
db = firestore.Client()
logging.basicConfig(level=logging.INFO)

TAGS_COLLECTION = db.collection('tags').document('jp_to_kr').collection('mappings')


@app.route("/tags", methods=["GET"])
def get_tags():
    try:
        tags = TAGS_COLLECTION.stream()
        results = []
        for doc in tags:
            data = doc.to_dict()
            results.append({
                "tag_jp": data.get("tag_jp"),
                "tag_kr": data.get("tag_kr"),
                "priority": data.get("priority", 10)
            })
        return jsonify(sorted(results, key=lambda x: x['priority'], reverse=True))
    except Exception as e:
        logging.error(f"Error fetching tags: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/tags", methods=["POST"])
def update_tag():
    try:
        data = request.get_json()
        tag_jp = data.get("tag_jp")
        tag_kr = data.get("tag_kr")
        priority = int(data.get("priority", 10))

        if not tag_jp or not tag_kr:
            return jsonify({"error": "tag_jp and tag_kr are required"}), 400

        TAGS_COLLECTION.document(tag_jp).set({
            "tag_jp": tag_jp,
            "tag_kr": tag_kr,
            "priority": priority
        })
        logging.info(f"Updated tag: {tag_jp} -> {tag_kr} ({priority})")
        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error updating tag: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return "Tag Editor API is running"
if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

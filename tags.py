from flask import Blueprint, request, jsonify
import logging

tag_bp = Blueprint("tags", __name__)
logger = logging.getLogger(__name__)

TAGS_COLLECTION = None

def init_tags(db):
    global TAGS_COLLECTION
    TAGS_COLLECTION = db.collection('tags').document('jp_to_kr').collection('mappings')

@tag_bp.route("/", methods=["GET"])
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

@tag_bp.route("/", methods=["POST"])
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

@tag_bp.route("/sync-tags", methods=["POST"])
def sync_tags_to_games():
    try:
        logger.info("Syncing tags to all game documents...")

        tag_map = {doc.id: doc.to_dict().get("tag_kr", doc.id) for doc in TAGS_COLLECTION.stream()}
        tag_priority = {doc.id: doc.to_dict().get("priority", 10) for doc in TAGS_COLLECTION.stream()}

        game_items = TAGS_COLLECTION.firestore.collection('games').document('rj').collection('items').stream()
        updated = 0

        for doc in game_items:
            data = doc.to_dict()
            tags_jp = data.get("tags_jp", [])
            if not tags_jp:
                continue

            tags_with_priority = [(tag_map.get(jp, "기타"), tag_priority.get(jp, 10)) for jp in tags_jp]
            tags_with_priority.sort(key=lambda x: x[1], reverse=True)
            tags_kr = [tag for tag, _ in tags_with_priority]
            best_tag = tags_kr[0] if tags_kr else "기타"

            doc.reference.update({
                "tags": tags_kr,
                "primary_tag": best_tag
            })
            updated += 1

        logger.info(f"Tags synced to {updated} games.")
        return jsonify({"updated": updated})
    except Exception as e:
        logger.error(f"Error in /sync-tags: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@tag_bp.route("/delete-slash", methods=["POST"])
def delete_slash_tags():
    try:
        logger.info("Deleting tags containing slashes...")
        deleted_count = 0

        # 모든 태그 문서 스트림
        tags = TAGS_COLLECTION.stream()
        for doc in tags:
            data = doc.to_dict()
            tag_jp = data.get("tag_jp", "")
            tag_kr = data.get("tag_kr", "")

            # tag_jp 또는 tag_kr에 슬래시(/)가 포함된 경우 삭제
            if "/" in tag_jp or "/" in tag_kr:
                doc.reference.delete()
                deleted_count += 1
                logger.info(f"Deleted tag: {tag_jp} -> {tag_kr}")

        logger.info(f"Deleted {deleted_count} tags with slashes.")
        return jsonify({"success": True, "deleted": deleted_count})
    except Exception as e:
        logger.error(f"Error in /delete-slash: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
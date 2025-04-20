from flask import Blueprint, request, jsonify
from google.cloud import firestore
import json, logging, re
import time

game_fs_bp  = Blueprint("game_fs", __name__)
logger = logging.getLogger(__name__)

# Firestore 클라이언트 초기화
try:
    db = firestore.Client()
    logger.info("Firestore 클라이언트 초기화 완료")
except Exception as e:
    logger.error(f"Firestore 초기화 실패: {e}")
    db = None

def get_firestore_path(platform, rj_code):
    """
    Firestore에 저장할 문서 ID 생성 (RJ 코드 정규화)
    """
    normalized_id = rj_code.upper().replace('-', '').replace('_', '').strip()
    return normalized_id

@game_fs_bp.route("/<platform>/<rj_code>", methods=["GET"])
def get_game(platform, rj_code):
    """
    특정 플랫폼/RJ코드에 해당하는 게임 정보 조회
    """
    doc_id = get_firestore_path(platform, rj_code)
    doc_ref = db.collection("games").document(platform).collection("items").document(doc_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return jsonify({"error": "찾을 수 없음"}), 404
    
    try:
        data = doc.to_dict()
        return jsonify(data)
    except Exception as e:
        logger.error(f"[GET] {platform}/{doc_id} 읽기 실패: {e}")
        return jsonify({"error": str(e)}), 500
    
@game_fs_bp.route("/<platform>", methods=["GET"])
def list_games(platform):
    """
    특정 플랫폼의 모든 게임 목록 조회
    """
    try:
        # Firestore 컬렉션에서 모든 문서 조회
        docs = db.collection("games").document(platform).collection("items").stream()
        game_list = []
        
        for doc in docs:
            try:
                data = doc.to_dict()
                # timestamp 필드가 있다면 문자열로 변환 (JSON 직렬화를 위해)
                if 'timestamp' in data and isinstance(data['timestamp'], (int, float)):
                    data['timestamp_str'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data['timestamp']))
                game_list.append(data)
            except Exception as e:
                logger.warning(f"⚠️ {doc.id} 파싱 실패: {e}")
        
        return jsonify(game_list)
    except Exception as e:
        logger.error(f"[LIST] {platform} 게임 목록 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500

@game_fs_bp.route("/<platform>/<rj_code>", methods=["POST"])
def update_game(platform, rj_code):
    """
    특정 게임 정보 업데이트 또는 새로 생성
    """
    doc_id = get_firestore_path(platform, rj_code)
    doc_ref = db.collection("games").document(platform).collection("items").document(doc_id)
    
    try:
        data = request.get_json()
        
        # 타임스탬프 추가
        if 'timestamp' not in data:
            data['timestamp'] = time.time()
            
        # Firestore에 저장 (merge=True로 기존 데이터와 병합)
        doc_ref.set(data, merge=True)
        logger.info(f"[POST] {platform}/{doc_id} 저장 성공")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"[POST] {platform}/{doc_id} 저장 실패: {e}")
        return jsonify({"error": str(e)}), 500

@game_fs_bp.route("/<platform>/<rj_code>", methods=["DELETE"])
def delete_game(platform, rj_code):
    """
    특정 게임 데이터 삭제
    """
    doc_id = get_firestore_path(platform, rj_code)
    doc_ref = db.collection("games").document(platform).collection("items").document(doc_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return jsonify({"error": "찾을 수 없음"}), 404
        
    try:
        doc_ref.delete()
        logger.info(f"[DELETE] {platform}/{doc_id} 삭제 성공")
        return jsonify({
            "success": True, 
            "message": f"게임 {rj_code} 삭제 완료"
        })
    except Exception as e:
        logger.error(f"[DELETE] {platform}/{doc_id} 삭제 실패: {e}")
        return jsonify({"error": str(e)}), 500

@game_fs_bp.route("/<platform>", methods=["DELETE"])
def delete_all_games(platform):
    """
    특정 플랫폼의 모든 게임 데이터 삭제
    """
    try:
        # 컬렉션의 모든 문서 조회
        collection_ref = db.collection("games").document(platform).collection("items")
        docs = collection_ref.stream()
        
        deleted_count = 0
        failed_count = 0
        
        # 모든 문서 순회하며 삭제
        for doc in docs:
            try:
                doc.reference.delete()
                deleted_count += 1
            except Exception as e:
                logger.warning(f"⚠️ {doc.id} 삭제 실패: {e}")
                failed_count += 1
        
        logger.info(f"[DELETE ALL] 플랫폼 {platform}: {deleted_count}개 삭제 완료, {failed_count}개 실패")
        
        if failed_count > 0:
            return jsonify({
                "success": True, 
                "message": f"{deleted_count}개 게임 삭제 완료, {failed_count}개 게임 삭제 실패"
            })
        else:
            return jsonify({
                "success": True, 
                "message": f"플랫폼 {platform}의 모든 게임({deleted_count}개) 삭제 완료"
            })
    except Exception as e:
        logger.error(f"[DELETE ALL] 플랫폼 {platform} 전체 삭제 실패: {e}")
        return jsonify({"error": str(e)}), 500

@game_fs_bp.route("/tag-stats", methods=["GET"])
def get_tag_stats():
    """
    모든 게임에서 사용된 태그의 통계 정보 조회
    """
    try:
        platform = request.args.get("platform", "rj")
        collection_ref = db.collection("games").document(platform).collection("items")
        
        # 모든 게임 문서 조회
        docs = collection_ref.stream()
        
        # 태그 카운팅
        tag_counts = {}
        game_count = 0
        
        for doc in docs:
            game_count += 1
            data = doc.to_dict()
            tags = data.get("tags", [])
            
            for tag in tags:
                if tag in tag_counts:
                    tag_counts[tag] += 1
                else:
                    tag_counts[tag] = 1
                    
        # 태그 사용 빈도 내림차순 정렬
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        
        result = {
            "total_games": game_count,
            "unique_tags": len(tag_counts),
            "tag_stats": [{"tag": tag, "count": count} for tag, count in sorted_tags]
        }
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"[TAG STATS] 태그 통계 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500

@game_fs_bp.route("/search", methods=["GET"])
def search_games():
    """
    게임 데이터 검색 (제목 또는 태그 기준)
    """
    try:
        platform = request.args.get("platform", "rj")
        query = request.args.get("query", "").strip().lower()
        tag = request.args.get("tag", "").strip()
        
        if not query and not tag:
            return jsonify({"error": "검색어 또는 태그를 입력하세요"}), 400
            
        collection_ref = db.collection("games").document(platform).collection("items")
        
        # 태그 기준 검색
        if tag:
            # Firestore는 배열 포함 쿼리를 지원하지만, 여기서는 모든 문서를 가져와서 필터링 
            # (실제 사용 시에는 색인과 쿼리 최적화 필요)
            docs = collection_ref.stream()
            results = []
            
            for doc in docs:
                data = doc.to_dict()
                tags = data.get("tags", [])
                
                if tag in tags:
                    results.append(data)
                    
            return jsonify(results)
            
        # 제목 기준 검색
        else:
            docs = collection_ref.stream()
            results = []
            
            for doc in docs:
                data = doc.to_dict()
                title_kr = data.get("title_kr", "").lower()
                title_jp = data.get("title_jp", "").lower()
                
                if query in title_kr or query in title_jp:
                    results.append(data)
                    
            return jsonify(results)
                
    except Exception as e:
        logger.error(f"[SEARCH] 게임 검색 실패: {e}")
        return jsonify({"error": str(e)}), 500
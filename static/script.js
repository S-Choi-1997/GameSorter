// API URL
const API_URL = "https://tagsite-28083845590.us-central1.run.app";

// DOM 요소 - 공통
const tabs = document.querySelectorAll('.tab');
const tabContents = document.querySelectorAll('.tab-content');
const toast = document.getElementById('toast');
const toastTitle = document.getElementById('toast-title');
const toastMessage = document.getElementById('toast-message');

// DOM 요소 - 태그 관리
const syncDbBtn = document.getElementById('sync-db-btn');
const syncConfirmModal = document.getElementById('sync-confirm-modal');
const cancelSyncBtn = document.getElementById('cancel-sync-btn');
const confirmSyncBtn = document.getElementById('confirm-sync-btn');
const tagSearchInput = document.getElementById('tag-search-input');
const newTagJp = document.getElementById('new-tag-jp');
const newTagKr = document.getElementById('new-tag-kr');
const newTagPriority = document.getElementById('new-tag-priority');
const addTagBtn = document.getElementById('add-tag-btn');
const tagsTableBody = document.getElementById('tags-table-body');

// DOM 요소 - 게임 데이터 관리
const platformSelect = document.getElementById('platform-select');
const gameCodeInput = document.getElementById('game-code-input');
const searchGameBtn = document.getElementById('search-game-btn');
const gameDataContainer = document.getElementById('game-data-container');
const gameForm = document.getElementById('game-form');
const gameTitle = document.getElementById('game-title');
const gameCircle = document.getElementById('game-circle');
const gameReleaseDate = document.getElementById('game-release-date');
const gamePrice = document.getElementById('game-price');
const gameDescription = document.getElementById('game-description');
const tagsJpContainer = document.getElementById('tags-jp-container');
const tagsKrContainer = document.getElementById('tags-kr-container');
const gamePrimaryTag = document.getElementById('game-primary-tag');
const saveGameBtn = document.getElementById('save-game-btn');

// 데이터 저장소
let tags = [];
let currentGame = null;
let currentGameCode = '';
let currentPlatform = 'rj';

// 탭 전환 이벤트
tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;
    
    // 활성 탭 변경
    tabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    
    // 탭 컨텐츠 변경
    tabContents.forEach(content => {
      content.classList.remove('active');
      if (content.id === `${tabId}-tab`) {
        content.classList.add('active');
      }
    });
  });
});

// DB 재설정 버튼 클릭
syncDbBtn.addEventListener('click', function() {
  syncConfirmModal.style.display = 'flex';
});

// 동기화 취소 버튼
cancelSyncBtn.addEventListener('click', function() {
  syncConfirmModal.style.display = 'none';
});

// 동기화 확인 버튼
confirmSyncBtn.addEventListener('click', syncDatabase);

// DB 동기화 함수
async function syncDatabase() {
  // 모달 닫기
  syncConfirmModal.style.display = 'none';
  
  // 버튼 로딩 상태로 변경
  syncDbBtn.disabled = true;
  syncDbBtn.innerHTML = '<span class="spinner"></span>동기화 중...';
  
  try {
    const response = await fetch(`${API_URL}/tags/sync-tags`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      }
    });
    
    if (!response.ok) {
      throw new Error('DB 동기화에 실패했습니다');
    }
    
    const data = await response.json();
    
    // 성공 메시지 표시
    showToast('성공', `DB 동기화 완료: ${data.updated}개 게임 문서 업데이트됨`, 'success');
  } catch (error) {
    console.error('DB 동기화 오류:', error);
    showToast('오류', '데이터베이스 동기화에 실패했습니다. 다시 시도해주세요.', 'error');
  } finally {
    // 버튼 상태 복원
    syncDbBtn.disabled = false;
    syncDbBtn.innerHTML = 'DB 재설정';
  }
}

// 검색 기능
tagSearchInput.addEventListener('input', filterTags);

// 새 태그 추가
addTagBtn.addEventListener('click', handleAddTag);

// 태그 가져오기
async function fetchTags() {
  try {
    const response = await fetch(`${API_URL}/tags/`);
    if (!response.ok) {
      throw new Error('태그를 가져오는데 실패했습니다');
    }
    
    tags = await response.json();
    renderTags();
  } catch (error) {
    console.error('태그 가져오기 오류:', error);
    showToast('오류', '태그를 가져오는데 실패했습니다. 다시 시도해주세요.', 'error');
    tagsTableBody.innerHTML = `
      <tr>
        <td colspan="4" class="loading-row">데이터를 불러올 수 없습니다</td>
      </tr>
    `;
  }
}

// 태그 업데이트
async function updateTag(tag) {
  try {
    const response = await fetch(`${API_URL}/tags/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(tag),
    });
    
    if (!response.ok) {
      throw new Error('태그 업데이트에 실패했습니다');
    }
    
    showToast('성공', `태그 업데이트: ${tag.tag_jp} → ${tag.tag_kr}`, 'success');
    await fetchTags();
  } catch (error) {
    console.error('태그 업데이트 오류:', error);
    showToast('오류', '태그 업데이트에 실패했습니다. 다시 시도해주세요.', 'error');
  }
}

// 태그 렌더링
function renderTags() {
  const searchQuery = tagSearchInput.value.toLowerCase();
  const filteredTags = tags.filter(tag => 
    tag.tag_jp.toLowerCase().includes(searchQuery) || 
    tag.tag_kr.toLowerCase().includes(searchQuery)
  );
  
  if (filteredTags.length === 0) {
    tagsTableBody.innerHTML = `
      <tr>
        <td colspan="4" class="loading-row">
          ${searchQuery ? '검색 결과가 없습니다' : '태그가 없습니다'}
        </td>
      </tr>
    `;
    return;
  }
  
  tagsTableBody.innerHTML = filteredTags.map(tag => `
    <tr data-tag-jp="${tag.tag_jp}">
      <td>${tag.tag_jp}</td>
      <td>
        <input type="text" value="${tag.tag_kr}" data-field="tag_kr">
      </td>
      <td>
        <input type="number" value="${tag.priority}" data-field="priority">
      </td>
      <td>
        <button class="save-btn">저장</button>
      </td>
    </tr>
  `).join('');
  
  // 저장 버튼에 이벤트 리스너 추가
  document.querySelectorAll('.save-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const row = this.closest('tr');
      const tagJp = row.dataset.tagJp;
      const tagKr = row.querySelector('[data-field="tag_kr"]').value;
      const priority = parseInt(row.querySelector('[data-field="priority"]').value);
      
      updateTag({
        tag_jp: tagJp,
        tag_kr: tagKr,
        priority: priority
      });
    });
  });
}

// 태그 필터링
function filterTags() {
  renderTags();
}

// 새 태그 추가
async function handleAddTag() {
  const tagJp = newTagJp.value.trim();
  const tagKr = newTagKr.value.trim();
  const priority = parseInt(newTagPriority.value);
  
  if (!tagJp || !tagKr) {
    showToast('오류', '일본어 태그와 한국어 태그는 필수입니다', 'error');
    return;
  }
  
  const newTag = {
    tag_jp: tagJp,
    tag_kr: tagKr,
    priority: priority
  };
  
  try {
    await updateTag(newTag);
    newTagJp.value = '';
    newTagKr.value = '';
    newTagPriority.value = '10';
  } catch (error) {
    console.error('태그 추가 오류:', error);
  }
}

// 게임 검색 버튼 클릭
searchGameBtn.addEventListener('click', searchGame);

// 게임 코드 입력 후 엔터키 처리
gameCodeInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    searchGame();
  }
});

// 게임 폼 제출 처리
gameForm.addEventListener('submit', function(e) {
  e.preventDefault();
  saveGame();
});

// 게임 검색 함수
async function searchGame() {
  const platform = platformSelect.value;
  let gameCode = gameCodeInput.value.trim();
  
  if (!gameCode) {
    showToast('오류', '게임 코드를 입력해주세요', 'error');
    return;
  }
  
  // RJ 코드 형식 정규화
  if (platform === 'rj' && !gameCode.toLowerCase().startsWith('rj')) {
    gameCode = 'RJ' + gameCode;
    gameCodeInput.value = gameCode;
  }
  
  currentPlatform = platform;
  currentGameCode = gameCode;
  
  try {
    searchGameBtn.disabled = true;
    searchGameBtn.innerHTML = '<span class="spinner"></span>검색 중...';
    
    const response = await fetch(`${API_URL}/games/${platform}/${gameCode}`);
    
    if (!response.ok) {
      if (response.status === 404) {
        showToast('알림', '게임을 찾을 수 없습니다. 새로운 게임 데이터를 생성합니다.', 'error');
        // 빈 게임 데이터 생성
        currentGame = {
          title: '',
          circle: '',
          release_date: '',
          price: 0,
          description: '',
          tags_jp: [],
          tags: [],
          primary_tag: ''
        };
      } else {
        throw new Error('게임 데이터를 가져오는데 실패했습니다');
      }
    } else {
      currentGame = await response.json();
    }
    
    // 게임 데이터 표시
    displayGameData();
    gameDataContainer.style.display = 'block';
  } catch (error) {
    console.error('게임 검색 오류:', error);
    showToast('오류', '게임 데이터를 가져오는데 실패했습니다. 다시 시도해주세요.', 'error');
  } finally {
    searchGameBtn.disabled = false;
    searchGameBtn.innerHTML = '검색';
  }
}

// 게임 데이터 표시 함수
function displayGameData() {
  if (!currentGame) return;
  
  gameTitle.value = currentGame.title || '';
  gameCircle.value = currentGame.circle || '';
  gameReleaseDate.value = currentGame.release_date || '';
  gamePrice.value = currentGame.price || 0;
  gameDescription.value = currentGame.description || '';
  gamePrimaryTag.value = currentGame.primary_tag || '';
  
  // 일본어 태그 표시
  renderTagChips(tagsJpContainer, currentGame.tags_jp || [], 'jp');
  
  // 한국어 태그 표시
  renderTagChips(tagsKrContainer, currentGame.tags || [], 'kr');
}

// 태그 칩 렌더링 함수
function renderTagChips(container, tagList, type) {
  container.innerHTML = '';
  
  if (!tagList || tagList.length === 0) {
    container.innerHTML = '<em>태그 없음</em>';
    return;
  }
  
  tagList.forEach(tag => {
    const chip = document.createElement('div');
    chip.className = 'tag-chip';
    chip.innerHTML = `
      ${tag}
      <span class="remove" data-tag="${tag}" data-type="${type}">&times;</span>
    `;
    container.appendChild(chip);
  });
  
  // 태그 삭제 이벤트 리스너 추가
  container.querySelectorAll('.remove').forEach(btn => {
    btn.addEventListener('click', function() {
      const tag = this.dataset.tag;
      const type = this.dataset.type;
      removeTag(tag, type);
    });
  });
}

// 태그 삭제 함수
function removeTag(tag, type) {
  if (type === 'jp') {
    currentGame.tags_jp = currentGame.tags_jp.filter(t => t !== tag);
  } else {
    currentGame.tags = currentGame.tags.filter(t => t !== tag);
  }
  
  // 태그 칩 다시 렌더링
  if (type === 'jp') {
    renderTagChips(tagsJpContainer, currentGame.tags_jp, 'jp');
  } else {
    renderTagChips(tagsKrContainer, currentGame.tags, 'kr');
  }
}

// 게임 저장 함수
async function saveGame() {
  if (!currentGame || !currentGameCode) {
    showToast('오류', '저장할 게임 데이터가 없습니다', 'error');
    return;
  }
  
  // 폼 데이터 수집
  currentGame.title = gameTitle.value;
  currentGame.circle = gameCircle.value;
  currentGame.release_date = gameReleaseDate.value;
  currentGame.price = parseInt(gamePrice.value) || 0;
  currentGame.description = gameDescription.value;
  
  try {
    saveGameBtn.disabled = true;
    saveGameBtn.innerHTML = '<span class="spinner"></span>저장 중...';
    
    const response = await fetch(`${API_URL}/games/${currentPlatform}/${currentGameCode}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(currentGame),
    });
    
    if (!response.ok) {
      throw new Error('게임 데이터 저장에 실패했습니다');
    }
    
    showToast('성공', '게임 데이터가 저장되었습니다', 'success');
  } catch (error) {
    console.error('게임 저장 오류:', error);
    showToast('오류', '게임 데이터 저장에 실패했습니다. 다시 시도해주세요.', 'error');
  } finally {
    saveGameBtn.disabled = false;
    saveGameBtn.innerHTML = '저장';
  }
}

// 토스트 메시지 표시
function showToast(title, message, type = 'success') {
  toastTitle.textContent = title;
  toastMessage.textContent = message;
  toast.className = `toast ${type}`;
  toast.style.display = 'block';
  
  setTimeout(() => {
    toast.style.display = 'none';
  }, 3000);
}

// 페이지 로드 시 태그 데이터 로드
document.addEventListener('DOMContentLoaded', function() {
  fetchTags();
});
// API URL
const API_URL = "https://tagsite-28083845590.us-central1.run.app"

// DOM 요소 - 공통
const tabs = document.querySelectorAll(".tab")
const tabContents = document.querySelectorAll(".tab-content")
const toast = document.getElementById("toast")
const toastTitle = document.getElementById("toast-title")
const toastMessage = document.getElementById("toast-message")

// DOM 요소 - 태그 관리
const syncDbBtn = document.getElementById("sync-db-btn")
const syncConfirmModal = document.getElementById("sync-confirm-modal")
const cancelSyncBtn = document.getElementById("cancel-sync-btn")
const confirmSyncBtn = document.getElementById("confirm-sync-btn")
const tagSearchInput = document.getElementById("tag-search-input")
const newTagJp = document.getElementById("new-tag-jp")
const newTagKr = document.getElementById("new-tag-kr")
const newTagPriority = document.getElementById("new-tag-priority")
const addTagBtn = document.getElementById("add-tag-btn")
const tagsTableBody = document.getElementById("tags-table-body")

// DOM 요소 - GCS 게임 목록
const gameListPlatformSelect = document.getElementById("game-list-platform-select")
const loadGamesBtn = document.getElementById("load-games-btn")
const gameListSearch = document.getElementById("game-list-search")
const gameList = document.getElementById("game-list")
const gameDetails = document.getElementById("game-details")
const deleteAllGamesBtn = document.getElementById("delete-all-games-btn")
const deleteGameConfirmModal = document.getElementById("delete-game-confirm-modal")
const deleteGameTitle = document.getElementById("delete-game-title")
const cancelDeleteGameBtn = document.getElementById("cancel-delete-game-btn")
const confirmDeleteGameBtn = document.getElementById("confirm-delete-game-btn")
const deleteAllGamesConfirmModal = document.getElementById("delete-all-games-confirm-modal")
const cancelDeleteAllGamesBtn = document.getElementById("cancel-delete-all-games-btn")
const confirmDeleteAllGamesBtn = document.getElementById("confirm-delete-all-games-btn")

// DOM 요소 - GCS 게임 검색
const platformSelect = document.getElementById("platform-select")
const gameCodeInput = document.getElementById("game-code-input")
const searchGameBtn = document.getElementById("search-game-btn")
const gameDataContainer = document.getElementById("game-data-container")
const gameForm = document.getElementById("game-form")
const gameTitle = document.getElementById("game-title")
const gameCircle = document.getElementById("game-circle")
const gameReleaseDate = document.getElementById("game-release-date")
const gamePrice = document.getElementById("game-price")
const gameDescription = document.getElementById("game-description")
const tagsJpContainer = document.getElementById("tags-jp-container")
const tagsKrContainer = document.getElementById("tags-kr-container")
const gamePrimaryTag = document.getElementById("game-primary-tag")
const saveGameBtn = document.getElementById("save-game-btn")

// DOM 요소 - Firestore 게임 목록
const fsGameListPlatformSelect = document.getElementById("fs-game-list-platform-select")
const fsLoadGamesBtn = document.getElementById("fs-load-games-btn")
const fsGameListSearch = document.getElementById("fs-game-list-search")
const fsGameList = document.getElementById("fs-game-list")
const fsGameDetails = document.getElementById("fs-game-details")
const fsDeleteAllGamesBtn = document.getElementById("fs-delete-all-games-btn")
const fsTagStatsBtn = document.getElementById("fs-tag-stats-btn")
const tagStatsModal = document.getElementById("tag-stats-modal")
const tagStatsContent = document.getElementById("tag-stats-content")
const closeTagStatsBtn = document.getElementById("close-tag-stats-btn")

// DOM 요소 - Firestore 게임 검색
const fsPlatformSelect = document.getElementById("fs-platform-select")
const fsGameCodeInput = document.getElementById("fs-game-code-input")
const fsSearchGameBtn = document.getElementById("fs-search-game-btn")
const fsTitlePlatformSelect = document.getElementById("fs-title-platform-select")
const fsTitleInput = document.getElementById("fs-title-input")
const fsSearchTitleBtn = document.getElementById("fs-search-title-btn")
const fsTagPlatformSelect = document.getElementById("fs-tag-platform-select")
const fsTagInput = document.getElementById("fs-tag-input")
const fsSearchTagBtn = document.getElementById("fs-search-tag-btn")
const fsSearchResults = document.getElementById("fs-search-results")
const fsGameDataContainer = document.getElementById("fs-game-data-container")
const fsGameForm = document.getElementById("fs-game-form")
const fsGameTitle = document.getElementById("fs-game-title")
const fsGameCircle = document.getElementById("fs-game-circle")
const fsGameReleaseDate = document.getElementById("fs-game-release-date")
const fsGamePrice = document.getElementById("fs-game-price")
const fsGameDescription = document.getElementById("fs-game-description")
const fsTagsJpContainer = document.getElementById("fs-tags-jp-container")
const fsTagsKrContainer = document.getElementById("fs-tags-kr-container")
const fsGamePrimaryTag = document.getElementById("fs-game-primary-tag")
const fsSaveGameBtn = document.getElementById("fs-save-game-btn")

// 데이터 저장소
let tags = []
let games = []
let filteredGames = []
let fsGames = []
let fsFiltredGames = []
let currentGame = null
let currentGameCode = ""
let currentPlatform = "rj"
let fsCurrentGame = null
let fsCurrentGameCode = ""
let fsCurrentPlatform = "rj"
let selectedGameIndex = -1
let fsSelectedGameIndex = -1

// 탭 전환 이벤트
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const tabId = tab.dataset.tab

    // 활성 탭 변경
    tabs.forEach((t) => t.classList.remove("active"))
    tab.classList.add("active")

    // 탭 컨텐츠 변경
    tabContents.forEach((content) => {
      content.classList.remove("active")
      if (content.id === `${tabId}-tab`) {
        content.classList.add("active")
      }
    })
  })
})

// DB 재설정 버튼 클릭
syncDbBtn.addEventListener("click", () => {
  syncConfirmModal.style.display = "flex"
})

// 동기화 취소 버튼
cancelSyncBtn.addEventListener("click", () => {
  syncConfirmModal.style.display = "none"
})

// 동기화 확인 버튼
confirmSyncBtn.addEventListener("click", syncDatabase)

// DB 동기화 함수
async function syncDatabase() {
  // 모달 닫기
  syncConfirmModal.style.display = "none"

  // 버튼 로딩 상태로 변경
  syncDbBtn.disabled = true
  syncDbBtn.innerHTML = '<span class="spinner"></span>동기화 중...'

  try {
    const response = await fetch(`${API_URL}/tags/sync-tags`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    })

    if (!response.ok) {
      throw new Error("DB 동기화에 실패했습니다")
    }

    const data = await response.json()

    // 성공 메시지 표시
    showToast("성공", `DB 동기화 완료: ${data.updated}개 게임 문서 업데이트됨`, "success")
  } catch (error) {
    console.error("DB 동기화 오류:", error)
    showToast("오류", "데이터베이스 동기화에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    // 버튼 상태 복원
    syncDbBtn.disabled = false
    syncDbBtn.innerHTML = "DB 재설정"
  }
}

// 검색 기능
tagSearchInput.addEventListener("input", filterTags)

// 새 태그 추가
addTagBtn.addEventListener("click", handleAddTag)

// 태그 가져오기
async function fetchTags() {
  try {
    const response = await fetch(`${API_URL}/tags/`)
    if (!response.ok) {
      throw new Error("태그를 가져오는데 실패했습니다")
    }

    tags = await response.json()
    renderTags()
  } catch (error) {
    console.error("태그 가져오기 오류:", error)
    showToast("오류", "태그를 가져오는데 실패했습니다. 다시 시도해주세요.", "error")
    tagsTableBody.innerHTML = `
      <tr>
        <td colspan="4" class="loading-row">데이터를 불러올 수 없습니다</td>
      </tr>
    `
  }
}

// 태그 업데이트
async function updateTag(tag) {
  try {
    const response = await fetch(`${API_URL}/tags/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(tag),
    })

    if (!response.ok) {
      throw new Error("태그 업데이트에 실패했습니다")
    }

    showToast("성공", `태그 업데이트: ${tag.tag_jp} → ${tag.tag_kr}`, "success")
    await fetchTags()
  } catch (error) {
    console.error("태그 업데이트 오류:", error)
    showToast("오류", "태그 업데이트에 실패했습니다. 다시 시도해주세요.", "error")
  }
}

// 태그 렌더링
function renderTags() {
  const searchQuery = tagSearchInput.value.toLowerCase()
  const filteredTags = tags.filter(
    (tag) => tag.tag_jp.toLowerCase().includes(searchQuery) || tag.tag_kr.toLowerCase().includes(searchQuery),
  )

  if (filteredTags.length === 0) {
    tagsTableBody.innerHTML = `
      <tr>
        <td colspan="4" class="loading-row">
          ${searchQuery ? "검색 결과가 없습니다" : "태그가 없습니다"}
        </td>
      </tr>
    `
    return
  }

  tagsTableBody.innerHTML = filteredTags
    .map(
      (tag) => `
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
  `,
    )
    .join("")

  // 저장 버튼에 이벤트 리스너 추가
  document.querySelectorAll(".save-btn").forEach((btn) => {
    btn.addEventListener("click", function () {
      const row = this.closest("tr")
      const tagJp = row.dataset.tagJp
      const tagKr = row.querySelector('[data-field="tag_kr"]').value
      const priority = Number.parseInt(row.querySelector('[data-field="priority"]').value)

      updateTag({
        tag_jp: tagJp,
        tag_kr: tagKr,
        priority: priority,
      })
    })
  })
}

// 태그 필터링
function filterTags() {
  renderTags()
}

// 새 태그 추가
async function handleAddTag() {
  const tagJp = newTagJp.value.trim()
  const tagKr = newTagKr.value.trim()
  const priority = Number.parseInt(newTagPriority.value)

  if (!tagJp || !tagKr) {
    showToast("오류", "일본어 태그와 한국어 태그는 필수입니다", "error")
    return
  }

  const newTag = {
    tag_jp: tagJp,
    tag_kr: tagKr,
    priority: priority,
  }

  try {
    await updateTag(newTag)
    newTagJp.value = ""
    newTagKr.value = ""
    newTagPriority.value = "10"
  } catch (error) {
    console.error("태그 추가 오류:", error)
  }
}

// ==================== GCS 게임 목록 관련 함수 ====================

// 게임 목록 불러오기 버튼 클릭
loadGamesBtn.addEventListener("click", loadGameList)

// 게임 목록 검색
gameListSearch.addEventListener("input", filterGameList)

// 게임 목록 불러오기
async function loadGameList() {
  const platform = gameListPlatformSelect.value

  gameList.innerHTML = '<div class="loading-message">로딩 중...</div>'

  try {
    loadGamesBtn.disabled = true
    loadGamesBtn.innerHTML = '<span class="spinner"></span>로딩 중...'

    const response = await fetch(`${API_URL}/games/${platform}`)

    if (!response.ok) {
      throw new Error("게임 목록을 가져오는데 실패했습니다")
    }

    games = await response.json()
    filteredGames = [...games]

    renderGameList()

    if (games.length > 0) {
      showToast("성공", `${games.length}개의 게임을 불러왔습니다`, "success")
    } else {
      showToast("알림", "게임이 없습니다", "error")
    }
  } catch (error) {
    console.error("게임 목록 불러오기 오류:", error)
    showToast("오류", "게임 목록을 가져오는데 실패했습니다. 다시 시도해주세요.", "error")
    gameList.innerHTML = '<div class="loading-message">데이터를 불러올 수 없습니다</div>'
  } finally {
    loadGamesBtn.disabled = false
    loadGamesBtn.innerHTML = "목록 불러오기"
  }
}

// 게임 목록 필터링
function filterGameList() {
  const searchQuery = gameListSearch.value.toLowerCase()

  filteredGames = games.filter(
    (game) =>
      (game.title_kr && game.title_kr.toLowerCase().includes(searchQuery)) ||
      (game.title_jp && game.title_jp.toLowerCase().includes(searchQuery)) ||
      (game.rj_code && game.rj_code.toLowerCase().includes(searchQuery)),
  )

  renderGameList()
}

// 게임 목록 렌더링
function renderGameList() {
  if (filteredGames.length === 0) {
    gameList.innerHTML = '<div class="loading-message">게임이 없습니다</div>'
    return
  }

  gameList.innerHTML = filteredGames
    .map(
      (game, index) => `
    <div class="game-list-item" data-index="${index}">
      <div class="game-list-item-title">${game.title_kr || game.title_jp || "제목 없음"}</div>
      <div class="game-list-item-code">${game.rj_code || ""}</div>
    </div>
  `,
    )
    .join("")

  // 게임 선택 이벤트 리스너 추가
  document.querySelectorAll(".game-list-item").forEach((item) => {
    item.addEventListener("click", function () {
      const index = Number.parseInt(this.dataset.index)
      selectGame(index)
    })
  })

  // 게임 상세 정보 초기화
  gameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
  selectedGameIndex = -1
}

// 게임 선택
function selectGame(index) {
  if (index < 0 || index >= filteredGames.length) return

  // 선택된 게임 항목 스타일 변경
  document.querySelectorAll(".game-list-item").forEach((item) => {
    item.classList.remove("active")
  })

  const selectedItem = document.querySelector(`.game-list-item[data-index="${index}"]`)
  if (selectedItem) {
    selectedItem.classList.add("active")
  }

  selectedGameIndex = index
  const game = filteredGames[index]

  // 게임 상세 정보 표시
  renderGameDetails(game)
}

// 게임 상세 정보 렌더링
function renderGameDetails(game) {
  if (!game) return

  const thumbnailUrl = game.thumbnail_url || "/placeholder.svg?height=120&width=120"
  const title = game.title_kr || game.title_jp || "제목 없음"
  const originalTitle = game.title_jp || ""
  const circle = game.maker || ""
  const releaseDate = game.release_date || ""
  const primaryTag = game.primary_tag || ""
  const tagsJp = game.tags_jp || []
  const tagsKr = game.tags || []
  const link = game.link || ""
  const rjCode = game.rj_code || ""

  gameDetails.innerHTML = `
    <div class="game-detail-header">
      <img src="${thumbnailUrl}" alt="${title}" class="game-thumbnail">
      <div class="game-detail-title">
        <h3>${title}</h3>
        ${originalTitle ? `<p>${originalTitle}</p>` : ""}
        <p>${circle}</p>
        <p>${rjCode}</p>
      </div>
    </div>
    
    <div class="game-detail-info">
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">출시일</span>
        <span>${releaseDate}</span>
      </div>
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">주요 태그</span>
        <span>${primaryTag}</span>
      </div>
      ${
        link
          ? `
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">링크</span>
        <a href="${link}" target="_blank" rel="noopener noreferrer">DLsite 페이지</a>
      </div>
      `
          : ""
      }
    </div>
    
    <div class="game-detail-tags">
      <h4>일본어 태그</h4>
      <div class="compact-tag-chips">
        ${tagsJp.map((tag) => `<span class="compact-tag-chip">${tag}</span>`).join("")}
      </div>
    </div>
    
    <div class="game-detail-tags">
      <h4>한국어 태그</h4>
      <div class="compact-tag-chips">
        ${tagsKr.map((tag) => `<span class="compact-tag-chip">${tag}</span>`).join("")}
      </div>
    </div>
    
    <div class="game-detail-actions">
      <button class="delete-btn" data-rjcode="${rjCode}">게임 삭제</button>
    </div>
  `

  // 삭제 버튼 이벤트 리스너 추가
  const deleteBtn = gameDetails.querySelector(".delete-btn")
  if (deleteBtn) {
    deleteBtn.addEventListener("click", function () {
      const rjCode = this.dataset.rjcode
      showDeleteGameConfirmModal(rjCode, title)
    })
  }
}

// 게임 삭제 확인 모달 표시
function showDeleteGameConfirmModal(rjCode, title) {
  deleteGameTitle.textContent = `${title} (${rjCode})`
  deleteGameConfirmModal.style.display = "flex"

  // 확인 버튼에 rjCode 데이터 설정
  confirmDeleteGameBtn.dataset.rjcode = rjCode
}

// 게임 삭제 취소 버튼
cancelDeleteGameBtn.addEventListener("click", () => {
  deleteGameConfirmModal.style.display = "none"
})

// 게임 삭제 확인 버튼
confirmDeleteGameBtn.addEventListener("click", function () {
  const rjCode = this.dataset.rjcode
  deleteGame(rjCode)
})

// 게임 삭제 함수
async function deleteGame(rjCode) {
  // 모달 닫기
  deleteGameConfirmModal.style.display = "none"

  const platform = gameListPlatformSelect.value

  try {
    const response = await fetch(`${API_URL}/games/${platform}/${rjCode}`, {
      method: "DELETE",
    })

    if (!response.ok) {
      throw new Error("게임 삭제에 실패했습니다")
    }

    const data = await response.json()

    // 성공 메시지 표시
    showToast("성공", `게임 삭제 완료: ${rjCode}`, "success")

    // 게임 목록 다시 불러오기
    loadGameList()

    // 게임 상세 정보 초기화
    gameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
    selectedGameIndex = -1
  } catch (error) {
    console.error("게임 삭제 오류:", error)
    showToast("오류", "게임 삭제에 실패했습니다. 다시 시도해주세요.", "error")
  }
}

// 전체 게임 삭제 버튼 클릭
deleteAllGamesBtn.addEventListener("click", () => {
  deleteAllGamesConfirmModal.style.display = "flex"
})

// 전체 게임 삭제 취소 버튼
cancelDeleteAllGamesBtn.addEventListener("click", () => {
  deleteAllGamesConfirmModal.style.display = "none"
})

// 전체 게임 삭제 확인 버튼
confirmDeleteAllGamesBtn.addEventListener("click", () => {
  deleteAllGames()
})

// 전체 게임 삭제 함수
async function deleteAllGames() {
  // 모달 닫기
  deleteAllGamesConfirmModal.style.display = "none"

  const platform = gameListPlatformSelect.value

  // 버튼 로딩 상태로 변경
  deleteAllGamesBtn.disabled = true
  deleteAllGamesBtn.innerHTML = '<span class="spinner"></span>삭제 중...'

  try {
    const response = await fetch(`${API_URL}/games/${platform}`, {
      method: "DELETE",
    })

    if (!response.ok) {
      throw new Error("전체 게임 삭제에 실패했습니다")
    }

    const data = await response.json()

    // 성공 메시지 표시
    showToast("성공", data.message, "success")

    // 게임 목록 초기화
    games = []
    filteredGames = []
    renderGameList()

    // 게임 상세 정보 초기화
    gameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
    selectedGameIndex = -1
  } catch (error) {
    console.error("전체 게임 삭제 오류:", error)
    showToast("오류", "전체 게임 삭제에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    // 버튼 상태 복원
    deleteAllGamesBtn.disabled = false
    deleteAllGamesBtn.innerHTML = "전체 삭제"
  }
}

// ==================== GCS 게임 검색 관련 함수 ====================

// 게임 검색 버튼 클릭
searchGameBtn.addEventListener("click", searchGame)

// 게임 코드 입력 후 엔터키 처리
gameCodeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault()
    searchGame()
  }
})

// 게임 폼 제출 처리
gameForm.addEventListener("submit", (e) => {
  e.preventDefault()
  saveGame()
})

// 게임 검색 함수
async function searchGame() {
  const platform = platformSelect.value
  let gameCode = gameCodeInput.value.trim()

  if (!gameCode) {
    showToast("오류", "게임 코드를 입력해주세요", "error")
    return
  }

  // RJ 코드 형식 정규화
  if (platform === "rj" && !gameCode.toLowerCase().startsWith("rj")) {
    gameCode = "RJ" + gameCode
    gameCodeInput.value = gameCode
  }

  currentPlatform = platform
  currentGameCode = gameCode

  try {
    searchGameBtn.disabled = true
    searchGameBtn.innerHTML = '<span class="spinner"></span>검색 중...'

    const response = await fetch(`${API_URL}/games/${platform}/${gameCode}`)

    if (!response.ok) {
      if (response.status === 404) {
        showToast("알림", "게임을 찾을 수 없습니다. 새로운 게임 데이터를 생성합니다.", "error")
        // 빈 게임 데이터 생성
        currentGame = {
          title: "",
          circle: "",
          release_date: "",
          price: 0,
          description: "",
          tags_jp: [],
          tags: [],
          primary_tag: "",
        }
      } else {
        throw new Error("게임 데이터를 가져오는데 실패했습니다")
      }
    } else {
      currentGame = await response.json()
    }

    // 게임 데이터 표시
    displayGameData()
    gameDataContainer.style.display = "block"
  } catch (error) {
    console.error("게임 검색 오류:", error)
    showToast("오류", "게임 데이터를 가져오는데 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    searchGameBtn.disabled = false
    searchGameBtn.innerHTML = "검색"
  }
}

// 게임 데이터 표시 함수
function displayGameData() {
  if (!currentGame) return

  gameTitle.value = currentGame.title || ""
  gameCircle.value = currentGame.circle || ""
  gameReleaseDate.value = currentGame.release_date || ""
  gamePrice.value = currentGame.price || 0
  gameDescription.value = currentGame.description || ""
  gamePrimaryTag.value = currentGame.primary_tag || ""

  // 일본어 태그 표시
  renderTagChips(tagsJpContainer, currentGame.tags_jp || [], "jp")

  // 한국어 태그 표시
  renderTagChips(tagsKrContainer, currentGame.tags || [], "kr")
}

// 태그 칩 렌더링 함수
function renderTagChips(container, tagList, type) {
  container.innerHTML = ""

  if (!tagList || tagList.length === 0) {
    container.innerHTML = "<em>태그 없음</em>"
    return
  }

  tagList.forEach((tag) => {
    const chip = document.createElement("div")
    chip.className = "tag-chip"
    chip.innerHTML = `
      ${tag}
      <span class="remove" data-tag="${tag}" data-type="${type}">&times;</span>
    `
    container.appendChild(chip)
  })

  // 태그 삭제 이벤트 리스너 추가
  container.querySelectorAll(".remove").forEach((btn) => {
    btn.addEventListener("click", function () {
      const tag = this.dataset.tag
      const type = this.dataset.type
      removeTag(tag, type)
    })
  })
}

// 태그 삭제 함수
function removeTag(tag, type) {
  if (type === "jp") {
    currentGame.tags_jp = currentGame.tags_jp.filter((t) => t !== tag)
  } else {
    currentGame.tags = currentGame.tags.filter((t) => t !== tag)
  }

  // 태그 칩 다시 렌더링
  if (type === "jp") {
    renderTagChips(tagsJpContainer, currentGame.tags_jp, "jp")
  } else {
    renderTagChips(tagsKrContainer, currentGame.tags, "kr")
  }
}

// 게임 저장 함수
async function saveGame() {
  if (!currentGame || !currentGameCode) {
    showToast("오류", "저장할 게임 데이터가 없습니다", "error")
    return
  }

  // 폼 데이터 수집
  currentGame.title = gameTitle.value
  currentGame.circle = gameCircle.value
  currentGame.release_date = gameReleaseDate.value
  currentGame.price = Number.parseInt(gamePrice.value) || 0
  currentGame.description = gameDescription.value

  try {
    saveGameBtn.disabled = true
    saveGameBtn.innerHTML = '<span class="spinner"></span>저장 중...'

    const response = await fetch(`${API_URL}/games/${currentPlatform}/${currentGameCode}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(currentGame),
    })

    if (!response.ok) {
      throw new Error("게임 데이터 저장에 실패했습니다")
    }

    showToast("성공", "게임 데이터가 저장되었습니다", "success")
  } catch (error) {
    console.error("게임 저장 오류:", error)
    showToast("오류", "게임 데이터 저장에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    saveGameBtn.disabled = false
    saveGameBtn.innerHTML = "저장"
  }
}

// ==================== Firestore 게임 목록 관련 함수 ====================

// 게임 목록 불러오기 버튼 클릭
fsLoadGamesBtn.addEventListener("click", loadFsGameList)

// 게임 목록 검색
fsGameListSearch.addEventListener("input", filterFsGameList)

// 태그 통계 버튼 클릭
fsTagStatsBtn.addEventListener("click", loadTagStats)

// 태그 통계 모달 닫기 버튼
closeTagStatsBtn.addEventListener("click", () => {
  tagStatsModal.style.display = "none"
})

// 게임 목록 불러오기
async function loadFsGameList() {
  const platform = fsGameListPlatformSelect.value

  fsGameList.innerHTML = '<div class="loading-message">로딩 중...</div>'

  try {
    fsLoadGamesBtn.disabled = true
    fsLoadGamesBtn.innerHTML = '<span class="spinner"></span>로딩 중...'

    const response = await fetch(`${API_URL}/games-fs/${platform}`)

    if (!response.ok) {
      throw new Error("게임 목록을 가져오는데 실패했습니다")
    }

    fsGames = await response.json()
    fsFiltredGames = [...fsGames]

    renderFsGameList()

    if (fsGames.length > 0) {
      showToast("성공", `${fsGames.length}개의 게임을 불러왔습니다`, "success")
    } else {
      showToast("알림", "게임이 없습니다", "error")
    }
  } catch (error) {
    console.error("게임 목록 불러오기 오류:", error)
    showToast("오류", "게임 목록을 가져오는데 실패했습니다. 다시 시도해주세요.", "error")
    fsGameList.innerHTML = '<div class="loading-message">데이터를 불러올 수 없습니다</div>'
  } finally {
    fsLoadGamesBtn.disabled = false
    fsLoadGamesBtn.innerHTML = "목록 불러오기"
  }
}

// 게임 목록 필터링
function filterFsGameList() {
  const searchQuery = fsGameListSearch.value.toLowerCase()

  fsFiltredGames = fsGames.filter(
    (game) =>
      (game.title_kr && game.title_kr.toLowerCase().includes(searchQuery)) ||
      (game.title_jp && game.title_jp.toLowerCase().includes(searchQuery)) ||
      (game.rj_code && game.rj_code.toLowerCase().includes(searchQuery)),
  )

  renderFsGameList()
}

// 게임 목록 렌더링
function renderFsGameList() {
  if (fsFiltredGames.length === 0) {
    fsGameList.innerHTML = '<div class="loading-message">게임이 없습니다</div>'
    return
  }

  fsGameList.innerHTML = fsFiltredGames
    .map(
      (game, index) => `
    <div class="game-list-item" data-index="${index}">
      <div class="game-list-item-title">${game.title_kr || game.title_jp || "제목 없음"}</div>
      <div class="game-list-item-code">${game.rj_code || ""}</div>
    </div>
  `,
    )
    .join("")

  // 게임 선택 이벤트 리스너 추가
  fsGameList.querySelectorAll(".game-list-item").forEach((item) => {
    item.addEventListener("click", function () {
      const index = Number.parseInt(this.dataset.index)
      selectFsGame(index)
    })
  })

  // 게임 상세 정보 초기화
  fsGameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
  fsSelectedGameIndex = -1
}

// 게임 선택
function selectFsGame(index) {
  if (index < 0 || index >= fsFiltredGames.length) return

  // 선택된 게임 항목 스타일 변경
  fsGameList.querySelectorAll(".game-list-item").forEach((item) => {
    item.classList.remove("active")
  })

  const selectedItem = fsGameList.querySelector(`.game-list-item[data-index="${index}"]`)
  if (selectedItem) {
    selectedItem.classList.add("active")
  }

  fsSelectedGameIndex = index
  const game = fsFiltredGames[index]

  // 게임 상세 정보 표시
  renderFsGameDetails(game)
}

// 게임 상세 정보 렌더링
function renderFsGameDetails(game) {
  if (!game) return

  const thumbnailUrl = game.thumbnail_url || "/placeholder.svg?height=120&width=120"
  const title = game.title_kr || game.title_jp || "제목 없음"
  const originalTitle = game.title_jp || ""
  const circle = game.maker || ""
  const releaseDate = game.release_date || ""
  const primaryTag = game.primary_tag || ""
  const tagsJp = game.tags_jp || []
  const tagsKr = game.tags || []
  const link = game.link || ""
  const rjCode = game.rj_code || ""
  const timestamp = game.timestamp_str || game.timestamp || ""

  fsGameDetails.innerHTML = `
    <div class="game-detail-header">
      <img src="${thumbnailUrl}" alt="${title}" class="game-thumbnail">
      <div class="game-detail-title">
        <h3>${title}</h3>
        ${originalTitle ? `<p>${originalTitle}</p>` : ""}
        <p>${circle}</p>
        <p>${rjCode}</p>
      </div>
    </div>
    
    <div class="game-detail-info">
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">출시일</span>
        <span>${releaseDate}</span>
      </div>
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">주요 태그</span>
        <span>${primaryTag}</span>
      </div>
      ${
        timestamp
          ? `
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">업데이트 시간</span>
        <span>${timestamp}</span>
      </div>
      `
          : ""
      }
      ${
        link
          ? `
      <div class="game-detail-info-item">
        <span class="game-detail-info-label">링크</span>
        <a href="${link}" target="_blank" rel="noopener noreferrer">DLsite 페이지</a>
      </div>
      `
          : ""
      }
    </div>
    
    <div class="game-detail-tags">
      <h4>일본어 태그</h4>
      <div class="compact-tag-chips">
        ${tagsJp.map((tag) => `<span class="compact-tag-chip">${tag}</span>`).join("")}
      </div>
    </div>
    
    <div class="game-detail-tags">
      <h4>한국어 태그</h4>
      <div class="compact-tag-chips">
        ${tagsKr.map((tag) => `<span class="compact-tag-chip">${tag}</span>`).join("")}
      </div>
    </div>
    
    <div class="game-detail-actions">
      <button class="delete-btn" data-rjcode="${rjCode}">게임 삭제</button>
    </div>
  `

  // 삭제 버튼 이벤트 리스너 추가
  const deleteBtn = fsGameDetails.querySelector(".delete-btn")
  if (deleteBtn) {
    deleteBtn.addEventListener("click", function () {
      const rjCode = this.dataset.rjcode
      showFsDeleteGameConfirmModal(rjCode, title)
    })
  }
}

// 게임 삭제 확인 모달 표시
function showFsDeleteGameConfirmModal(rjCode, title) {
  deleteGameTitle.textContent = `${title} (${rjCode})`
  deleteGameConfirmModal.style.display = "flex"

  // 확인 버튼에 rjCode 데이터 설정
  confirmDeleteGameBtn.dataset.rjcode = rjCode
  confirmDeleteGameBtn.dataset.source = "firestore"
}

// 게임 삭제 함수 (Firestore)
async function deleteFsGame(rjCode) {
  // 모달 닫기
  deleteGameConfirmModal.style.display = "none"

  const platform = fsGameListPlatformSelect.value

  try {
    const response = await fetch(`${API_URL}/games-fs/${platform}/${rjCode}`, {
      method: "DELETE",
    })

    if (!response.ok) {
      throw new Error("게임 삭제에 실패했습니다")
    }

    const data = await response.json()

    // 성공 메시지 표시
    showToast("성공", `게임 삭제 완료: ${rjCode}`, "success")

    // 게임 목록 다시 불러오기
    loadFsGameList()

    // 게임 상세 정보 초기화
    fsGameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
    fsSelectedGameIndex = -1
  } catch (error) {
    console.error("게임 삭제 오류:", error)
    showToast("오류", "게임 삭제에 실패했습니다. 다시 시도해주세요.", "error")
  }
}

// 게임 삭제 확인 버튼 이벤트 수정
confirmDeleteGameBtn.addEventListener("click", function () {
  const rjCode = this.dataset.rjcode
  const source = this.dataset.source

  if (source === "firestore") {
    deleteFsGame(rjCode)
  } else {
    deleteGame(rjCode)
  }
})

// 전체 게임 삭제 버튼 클릭 (Firestore)
fsDeleteAllGamesBtn.addEventListener("click", () => {
  deleteAllGamesConfirmModal.style.display = "flex"
  confirmDeleteAllGamesBtn.dataset.source = "firestore"
})

// 전체 게임 삭제 확인 버튼 이벤트 수정
confirmDeleteAllGamesBtn.addEventListener("click", function () {
  const source = this.dataset.source

  if (source === "firestore") {
    deleteAllFsGames()
  } else {
    deleteAllGames()
  }
})

// 전체 게임 삭제 함수 (Firestore)
async function deleteAllFsGames() {
  // 모달 닫기
  deleteAllGamesConfirmModal.style.display = "none"

  const platform = fsGameListPlatformSelect.value

  // 버튼 로딩 상태로 변경
  fsDeleteAllGamesBtn.disabled = true
  fsDeleteAllGamesBtn.innerHTML = '<span class="spinner"></span>삭제 중...'

  try {
    const response = await fetch(`${API_URL}/games-fs/${platform}`, {
      method: "DELETE",
    })

    if (!response.ok) {
      throw new Error("전체 게임 삭제에 실패했습니다")
    }

    const data = await response.json()

    // 성공 메시지 표시
    showToast("성공", data.message, "success")

    // 게임 목록 초기화
    fsGames = []
    fsFiltredGames = []
    renderFsGameList()

    // 게임 상세 정보 초기화
    fsGameDetails.innerHTML = '<div class="no-selection-message">왼쪽 목록에서 게임을 선택하세요</div>'
    fsSelectedGameIndex = -1
  } catch (error) {
    console.error("전체 게임 삭제 오류:", error)
    showToast("오류", "전체 게임 삭제에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    // 버튼 상태 복원
    fsDeleteAllGamesBtn.disabled = false
    fsDeleteAllGamesBtn.innerHTML = "전체 삭제"
  }
}

// 태그 통계 불러오기
async function loadTagStats() {
  const platform = fsGameListPlatformSelect.value

  tagStatsContent.innerHTML = '<div class="loading-message">통계 데이터를 불러오는 중...</div>'
  tagStatsModal.style.display = "flex"

  try {
    const response = await fetch(`${API_URL}/games-fs/tag-stats?platform=${platform}`)

    if (!response.ok) {
      throw new Error("태그 통계를 가져오는데 실패했습니다")
    }

    const data = await response.json()

    // 태그 통계 렌더링
    renderTagStats(data)
  } catch (error) {
    console.error("태그 통계 불러오기 오류:", error)
    tagStatsContent.innerHTML = '<div class="loading-message">통계 데이터를 불러올 수 없습니다</div>'
  }
}

// 태그 통계 렌더링
function renderTagStats(data) {
  const totalGames = data.total_games
  const uniqueTags = data.unique_tags
  const tagStats = data.tag_stats

  // 가장 많이 사용된 태그의 카운트 (최대값)
  const maxCount = tagStats.length > 0 ? tagStats[0].count : 0

  let html = `
    <div class="tag-stats-summary">
      <p>총 게임 수: <strong>${totalGames}</strong></p>
      <p>고유 태그 수: <strong>${uniqueTags}</strong></p>
    </div>
    <div class="tag-stats-list">
  `

  tagStats.forEach((item) => {
    const percentage = maxCount > 0 ? (item.count / maxCount) * 100 : 0

    html += `
      <div class="tag-stats-item">
        <div>
          <span class="tag-stats-name">${item.tag}</span>
          <div class="tag-stats-bar">
            <div class="tag-stats-bar-fill" style="width: ${percentage}%"></div>
          </div>
        </div>
        <span class="tag-stats-count">${item.count}</span>
      </div>
    `
  })

  html += "</div>"

  tagStatsContent.innerHTML = html
}

// ==================== Firestore 게임 검색 관련 함수 ====================

// 게임 코드로 검색 버튼 클릭
fsSearchGameBtn.addEventListener("click", searchFsGame)

// 제목으로 검색 버튼 클릭
fsSearchTitleBtn.addEventListener("click", searchFsGameByTitle)

// 태그로 검색 버튼 클릭
fsSearchTagBtn.addEventListener("click", searchFsGameByTag)

// 게임 코드 입력 후 엔터키 처리
fsGameCodeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault()
    searchFsGame()
  }
})

// 제목 입력 후 엔터키 처리
fsTitleInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault()
    searchFsGameByTitle()
  }
})

// 태그 입력 후 엔터키 처리
fsTagInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault()
    searchFsGameByTag()
  }
})

// 게임 폼 제출 처리
fsGameForm.addEventListener("submit", (e) => {
  e.preventDefault()
  saveFsGame()
})

// 게임 코드로 검색 함수
async function searchFsGame() {
  const platform = fsPlatformSelect.value
  let gameCode = fsGameCodeInput.value.trim()

  if (!gameCode) {
    showToast("오류", "게임 코드를 입력해주세요", "error")
    return
  }

  // RJ 코드 형식 정규화
  if (platform === "rj" && !gameCode.toLowerCase().startsWith("rj")) {
    gameCode = "RJ" + gameCode
    fsGameCodeInput.value = gameCode
  }

  fsCurrentPlatform = platform
  fsCurrentGameCode = gameCode

  try {
    fsSearchGameBtn.disabled = true
    fsSearchGameBtn.innerHTML = '<span class="spinner"></span>검색 중...'

    const response = await fetch(`${API_URL}/games-fs/${platform}/${gameCode}`)

    if (!response.ok) {
      if (response.status === 404) {
        showToast("알림", "게임을 찾을 수 없습니다. 새로운 게임 데이터를 생성합니다.", "error")
        // 빈 게임 데이터 생성
        fsCurrentGame = {
          title: "",
          circle: "",
          release_date: "",
          price: 0,
          description: "",
          tags_jp: [],
          tags: [],
          primary_tag: "",
        }
      } else {
        throw new Error("게임 데이터를 가져오는데 실패했습니다")
      }
    } else {
      fsCurrentGame = await response.json()
    }

    // 게임 데이터 표시
    displayFsGameData()
    fsGameDataContainer.style.display = "block"
    fsSearchResults.style.display = "none"
  } catch (error) {
    console.error("게임 검색 오류:", error)
    showToast("오류", "게임 데이터를 가져오는데 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    fsSearchGameBtn.disabled = false
    fsSearchGameBtn.innerHTML = "검색"
  }
}

// 제목으로 게임 검색 함수
async function searchFsGameByTitle() {
  const platform = fsTitlePlatformSelect.value
  const query = fsTitleInput.value.trim()

  if (!query) {
    showToast("오류", "검색어를 입력해주세요", "error")
    return
  }

  try {
    fsSearchTitleBtn.disabled = true
    fsSearchTitleBtn.innerHTML = '<span class="spinner"></span>검색 중...'

    const response = await fetch(`${API_URL}/games-fs/search?platform=${platform}&query=${encodeURIComponent(query)}`)

    if (!response.ok) {
      throw new Error("게임 검색에 실패했습니다")
    }

    const results = await response.json()

    // 검색 결과 표시
    renderFsSearchResults(results)
    fsGameDataContainer.style.display = "none"
    fsSearchResults.style.display = "block"
  } catch (error) {
    console.error("게임 검색 오류:", error)
    showToast("오류", "게임 검색에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    fsSearchTitleBtn.disabled = false
    fsSearchTitleBtn.innerHTML = "검색"
  }
}

// 태그로 게임 검색 함수
async function searchFsGameByTag() {
  const platform = fsTagPlatformSelect.value
  const tag = fsTagInput.value.trim()

  if (!tag) {
    showToast("오류", "태그를 입력해주세요", "error")
    return
  }

  try {
    fsSearchTagBtn.disabled = true
    fsSearchTagBtn.innerHTML = '<span class="spinner"></span>검색 중...'

    const response = await fetch(`${API_URL}/games-fs/search?platform=${platform}&tag=${encodeURIComponent(tag)}`)

    if (!response.ok) {
      throw new Error("게임 검색에 실패했습니다")
    }

    const results = await response.json()

    // 검색 결과 표시
    renderFsSearchResults(results)
    fsGameDataContainer.style.display = "none"
    fsSearchResults.style.display = "block"
  } catch (error) {
    console.error("게임 검색 오류:", error)
    showToast("오류", "게임 검색에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    fsSearchTagBtn.disabled = false
    fsSearchTagBtn.innerHTML = "검색"
  }
}

// 검색 결과 렌더링
function renderFsSearchResults(results) {
  if (!results || results.length === 0) {
    fsSearchResults.innerHTML = '<div class="no-results-message">검색 결과가 없습니다</div>'
    return
  }

  let html = ""

  results.forEach((game) => {
    const title = game.title_kr || game.title_jp || "제목 없음"
    const rjCode = game.rj_code || ""
    const circle = game.maker || ""
    const tags = game.tags || []

    html += `
      <div class="search-result-item" data-rjcode="${rjCode}" data-platform="${game.platform || "rj"}">
        <div class="search-result-title">${title}</div>
        <div class="search-result-info">${rjCode} | ${circle}</div>
        <div class="compact-tag-chips">
          ${tags
            .slice(0, 5)
            .map((tag) => `<span class="compact-tag-chip">${tag}</span>`)
            .join("")}
          ${tags.length > 5 ? `<span class="compact-tag-chip">+${tags.length - 5}</span>` : ""}
        </div>
      </div>
    `
  })

  fsSearchResults.innerHTML = html

  // 검색 결과 클릭 이벤트 리스너 추가
  fsSearchResults.querySelectorAll(".search-result-item").forEach((item) => {
    item.addEventListener("click", function () {
      const rjCode = this.dataset.rjcode
      const platform = this.dataset.platform

      // 게임 코드 입력 필드에 값 설정
      fsPlatformSelect.value = platform
      fsGameCodeInput.value = rjCode

      // 게임 검색 실행
      searchFsGame()
    })
  })
}

// 게임 데이터 표시 함수 (Firestore)
function displayFsGameData() {
  if (!fsCurrentGame) return

  fsGameTitle.value = fsCurrentGame.title || ""
  fsGameCircle.value = fsCurrentGame.circle || ""
  fsGameReleaseDate.value = fsCurrentGame.release_date || ""
  fsGamePrice.value = fsCurrentGame.price || 0
  fsGameDescription.value = fsCurrentGame.description || ""
  fsGamePrimaryTag.value = fsCurrentGame.primary_tag || ""

  // 일본어 태그 표시
  renderFsTagChips(fsTagsJpContainer, fsCurrentGame.tags_jp || [], "jp")

  // 한국어 태그 표시
  renderFsTagChips(fsTagsKrContainer, fsCurrentGame.tags || [], "kr")
}

// 태그 칩 렌더링 함수 (Firestore)
function renderFsTagChips(container, tagList, type) {
  container.innerHTML = ""

  if (!tagList || tagList.length === 0) {
    container.innerHTML = "<em>태그 없음</em>"
    return
  }

  tagList.forEach((tag) => {
    const chip = document.createElement("div")
    chip.className = "tag-chip"
    chip.innerHTML = `
      ${tag}
      <span class="remove" data-tag="${tag}" data-type="${type}">&times;</span>
    `
    container.appendChild(chip)
  })

  // 태그 삭제 이벤트 리스너 추가
  container.querySelectorAll(".remove").forEach((btn) => {
    btn.addEventListener("click", function () {
      const tag = this.dataset.tag
      const type = this.dataset.type
      removeFsTag(tag, type)
    })
  })
}

// 태그 삭제 함수 (Firestore)
function removeFsTag(tag, type) {
  if (type === "jp") {
    fsCurrentGame.tags_jp = fsCurrentGame.tags_jp.filter((t) => t !== tag)
  } else {
    fsCurrentGame.tags = fsCurrentGame.tags.filter((t) => t !== tag)
  }

  // 태그 칩 다시 렌더링
  if (type === "jp") {
    renderFsTagChips(fsTagsJpContainer, fsCurrentGame.tags_jp, "jp")
  } else {
    renderFsTagChips(fsTagsKrContainer, fsCurrentGame.tags, "kr")
  }
}

// 게임 저장 함수 (Firestore)
async function saveFsGame() {
  if (!fsCurrentGame || !fsCurrentGameCode) {
    showToast("오류", "저장할 게임 데이터가 없습니다", "error")
    return
  }

  // 폼 데이터 수집
  fsCurrentGame.title = fsGameTitle.value
  fsCurrentGame.circle = fsGameCircle.value
  fsCurrentGame.release_date = fsGameReleaseDate.value
  fsCurrentGame.price = Number.parseInt(fsGamePrice.value) || 0
  fsCurrentGame.description = fsGameDescription.value

  try {
    fsSaveGameBtn.disabled = true
    fsSaveGameBtn.innerHTML = '<span class="spinner"></span>저장 중...'

    const response = await fetch(`${API_URL}/games-fs/${fsCurrentPlatform}/${fsCurrentGameCode}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(fsCurrentGame),
    })

    if (!response.ok) {
      throw new Error("게임 데이터 저장에 실패했습니다")
    }

    showToast("성공", "게임 데이터가 저장되었습니다", "success")
  } catch (error) {
    console.error("게임 저장 오류:", error)
    showToast("오류", "게임 데이터 저장에 실패했습니다. 다시 시도해주세요.", "error")
  } finally {
    fsSaveGameBtn.disabled = false
    fsSaveGameBtn.innerHTML = "저장"
  }
}

// 토스트 메시지 표시 함수
function showToast(title, message, type = "info") {
  toastTitle.textContent = title
  toastMessage.textContent = message

  toast.classList.remove("info", "success", "error")
  toast.classList.add(type)

  toast.classList.add("show")

  setTimeout(() => {
    toast.classList.remove("show")
  }, 3000)
}

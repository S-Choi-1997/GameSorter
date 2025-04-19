@echo off
cd /d E:\Projects\game-sort

:: 이전 빌드 결과물 삭제
echo 🔄 기존 dist, build, spec 파일 삭제 중...
if exist dist (
    rmdir /s /q dist
    echo ✅ dist 삭제 완료
)
if exist build (
    rmdir /s /q build
    echo ✅ build 삭제 완료
)
if exist 방주이름생성기.spec (
    del /q 방주이름생성기.spec
    echo ✅ 방주이름생성기.spec 삭제 완료
)

:: PyInstaller로 빌드
pyinstaller --onefile --windowed ^
--name=방주이름생성기 ^
--icon=app.ico ^
--hidden-import=PySide6 ^
--hidden-import=requests ^
--hidden-import=bs4 ^
--hidden-import=soupsieve ^
--hidden-import=lxml ^
--hidden-import=html5lib ^
core.py


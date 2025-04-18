@echo off
cd /d E:\Projects\game-sort

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

pause

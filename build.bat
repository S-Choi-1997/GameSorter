@echo off
cd d EProjectsgame-sort
pyinstaller --onefile --windowed --name=방주이름생성기 --icon=app.ico --hidden-import=PySide6 --hidden-import=openai --hidden-import=requests --hidden-import=bs4 gamesort.py
pause

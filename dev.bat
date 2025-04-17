@echo off
set CONTAINER_NAME=game-dev

echo Checking for existing container...

docker ps -a --format "{{.Names}}" | findstr /I %CONTAINER_NAME% > nul

if %errorlevel%==0 (
    echo Re-attaching to existing container...
    docker start -ai %CONTAINER_NAME%
) else (
    echo Creating new development container...
    docker run -it --name %CONTAINER_NAME% -v %cd%:/app -w /app python:3.11 bash
)

pause

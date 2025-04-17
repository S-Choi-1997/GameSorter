@echo off
start cmd /k "docker run -it -v %cd%:/app -w /app python:3.11 bash"
@echo off
cd /d "%~dp0"
python timeline_maker.py
if errorlevel 1 pause

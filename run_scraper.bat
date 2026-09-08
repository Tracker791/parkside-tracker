@echo off
cd /d "%~dp0"
python scraper.py >> scraper_log.txt 2>&1

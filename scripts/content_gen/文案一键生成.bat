@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   EvalShield article generator (one click)
echo   Each run = a FRESH short article (new topic + new pain point)
echo   Output: output\[today]\   (same-day runs do NOT overwrite)
echo   Chinese tips are printed by the Python script below.
echo ============================================================
echo.

rem Pick an available Python (prefer "python", fall back to "py -3")
set "PYCMD=python"
where python >nul 2>&1
if errorlevel 1 set "PYCMD=py -3"

rem Key is auto-loaded from a same-folder .env (script handles it). Nudge if absent.
if not exist ".env" if not defined OPENAI_API_KEY (
  echo [hint] No .env and OPENAI_API_KEY is not set. Real runs need a key:
  echo        copy .env.example to .env and fill OPENAI_API_KEY.
  echo        Preview without a key:  run this bat with  --dry-run
  echo.
)

%PYCMD% generate_article.py %*

if errorlevel 1 (
  echo.
  echo [FAILED] See the error above. Common causes: missing OPENAI_API_KEY,
  echo          network blocked, or Python not installed.
) else (
  echo.
  echo [DONE] A new article was generated. Grab it from the output\[today]\ folder above.
)

echo.
pause
endlocal

@echo off
REM Convenience runner - does NOT need the venv to be "activated".
REM Usage:  run              -> run the full ingestion pipeline
REM         run test          -> run the test suite
REM         run nb            -> execute notebooks/01_ingestion.ipynb
setlocal
set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [run] .venv not found. Create it first:
  echo     py -3.12 -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -e ".[dev]"
  exit /b 1
)
if "%1"=="test" (
  "%PY%" -m pytest %2 %3 %4 %5
) else if "%1"=="nb" (
  "%PY%" -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_ingestion.ipynb
) else (
  "%PY%" -m pricelab.ingest --all %1 %2 %3 %4 %5
)
endlocal

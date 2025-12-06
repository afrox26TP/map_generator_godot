@echo off
echo ===============================
echo Activating environment...
echo ===============================
call venv\Scripts\activate.bat

echo ===============================
echo Running build_map.py...
echo ===============================
python build_map.py

echo ===============================
echo Finished.
echo ===============================
pause

@echo off
echo ===============================
echo Creating virtual environment...
echo ===============================
python -m venv venv

echo ===============================
echo Activating venv...
echo ===============================
call venv\Scripts\activate.bat

echo ===============================
echo Installing requirements...
echo ===============================
pip install --upgrade pip
pip install -r requirements.txt

echo ===============================
echo Installation complete!
echo ===============================
pause

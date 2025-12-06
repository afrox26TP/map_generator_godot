@echo off
echo ======================================
echo Creating ZIP package for deployment...
echo ======================================

set ZIPNAME=build_map_package.zip

REM delete previous ZIP if exists
if exist %ZIPNAME% del %ZIPNAME%

powershell Compress-Archive -Path * -DestinationPath %ZIPNAME%

echo.
echo ZIP package created: %ZIPNAME%
echo ======================================
pause

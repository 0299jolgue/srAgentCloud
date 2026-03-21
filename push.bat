@echo off
setlocal

:: Ask for commit message
set /p msg="Enter commit message (or press Enter for 'quick commit'): "

:: Check if message is empty
if "%msg%"=="" set msg=quick commit

:: Run Git commands
echo.
echo --- Adding files ---
git add .

echo --- Committing with message: "%msg%" ---
git commit -m "%msg%"

echo --- Pushing to Gitea ---
git push

echo.
echo Done!
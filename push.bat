@echo off
chcp 65001

echo 변경된 파일 확인 중...
git status

echo.

set /p msg=커밋 메시지 입력: 

if "%msg%"=="" (
    echo 커밋 취소됨
    pause
    exit
)

git add .

git diff --cached --quiet
if %errorlevel%==0 (
    echo 커밋할 변경사항 없음
    pause
    exit
)

git commit -m "%msg%"
git push

echo 완료!
pause
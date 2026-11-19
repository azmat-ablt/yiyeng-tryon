@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
set "GIT=D:\traewenjian\workbudyyunxing\WorkBuddy\resources\vendor\PortableGit\mingw64\bin\git.exe"

echo ============================================
echo    衣影 YIYING  更新并推送到 GitHub
echo ============================================
echo.

if not exist "%GIT%" (
  echo [错误] 找不到 git 程序：
  echo %GIT%
  echo 可能是 WorkBuddy 升级导致路径变化，请把新路径填入本文件第 5 行。
  pause
  exit /b 1
)

echo 当前改动：
"%GIT%" status --short
echo.
echo 提示：加速器 Watt Toolkit 必须先开启并勾选 GitHub 加速，否则推送会失败。
echo.

set "MSG="
set /p "MSG=请输入这次改了什么（直接回车就用默认说明）: "
if "%MSG%"=="" set "MSG=chore: 日常更新"

"%GIT%" add -A
"%GIT%" commit -m "%MSG%" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [跳过] 没有检测到改动，无需提交。
  pause
  exit /b 0
)

echo.
echo 正在推送...
"%GIT%" push origin main
if errorlevel 1 (
  echo.
  echo [失败] 推送没有成功。请检查：
  echo   1) Watt Toolkit 是否已开启并勾选了 GitHub 加速
  echo   2) 弹出的 GitHub 登录窗口是否完成授权
  pause
  exit /b 1
)

echo.
echo [完成] 已更新：https://github.com/azmat-ablt/yiyeng-tryon
pause
exit /b 0

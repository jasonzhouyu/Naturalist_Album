@echo off
REM Lightroom Import Handler — 接收 lrimport://UNC-PATH 并复制路径 + 打开 Lightroom
setlocal enabledelayedexpansion

set "raw=%~1"
REM 去掉 lrimport:// 前缀
set "path=!raw:lrimport://=\\!"
REM 恢复反斜杠
set "path=!path:/=\!"

REM 复制到剪贴板（用 PowerShell）
echo %path% | clip

REM 尝试打开 Lightroom（找最新版本）
set "LR="
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\Lightroom.exe" set "LR=%LOCALAPPDATA%\Microsoft\WindowsApps\Lightroom.exe"
if exist "C:\Program Files\Adobe\Adobe Lightroom Classic\Lightroom.exe" set "LR=C:\Program Files\Adobe\Adobe Lightroom Classic\Lightroom.exe"
if exist "C:\Program Files\Adobe\Adobe Lightroom\Lightroom.exe" set "LR=C:\Program Files\Adobe\Adobe Lightroom\Lightroom.exe"
if exist "C:\Program Files\Adobe\Lightroom Classic\Lightroom.exe" set "LR=C:\Program Files\Adobe\Lightroom Classic\Lightroom.exe"

if defined LR (
    start "" "%LR%"
) else (
    REM 找不到 Lightroom，打开文件所在文件夹
    explorer /select,"%path%"
)

REM 显示提示（仅命令行窗口可见）
echo Lightroom 已打开，按 Ctrl+Shift+I 进入导入面板，然后 Ctrl+V 粘贴路径

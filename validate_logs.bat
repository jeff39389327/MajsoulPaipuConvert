@echo off
REM validate_logs.exe is a Rust + embedded CPython 3.10 tool; it needs python310.dll
REM at runtime. This machine only has Python 3.11, so we prepend a no-install
REM Python 3.10 embeddable folder to PATH for THIS invocation only (no global change).
REM Usage (same as before, just call this .bat):
REM     .\validate_logs.bat mahjong_logs\mjai
setlocal
set "PATH=C:\Users\usert\tools\python310-embed;%PATH%"
"%~dp0validate_logs.exe" %*
exit /b %ERRORLEVEL%

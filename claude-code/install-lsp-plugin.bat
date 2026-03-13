@echo off
REM install-lsp-plugin.bat — Install delphi-lsp plugin for Claude Code (Windows)
REM
REM Usage:
REM   install-lsp-plugin.bat <path-to-delphi-lsp-server.exe> <path-to-delphi_symbols.db>
REM
REM Both paths must be absolute Windows paths.
REM
REM Example:
REM   install-lsp-plugin.bat "C:\tools\delphi-lsp-server.exe" "C:\tools\delphi_symbols.db"

setlocal enabledelayedexpansion

if "%~2"=="" (
    echo Usage: %~nx0 ^<path-to-delphi-lsp-server.exe^> ^<path-to-delphi_symbols.db^>
    echo.
    echo Both paths must be absolute Windows paths.
    echo Example: %~nx0 "C:\tools\delphi-lsp-server.exe" "C:\tools\delphi_symbols.db"
    exit /b 1
)

set "SERVER_PATH=%~1"
set "DB_PATH=%~2"
set "PLUGIN_DIR=%USERPROFILE%\.claude\skills\delphi-lsp"

echo Installing delphi-lsp plugin for Claude Code...
echo   Server:   %SERVER_PATH%
echo   Database: %DB_PATH%
echo   Target:   %PLUGIN_DIR%
echo.

REM --- Verify server exists ---
if not exist "%SERVER_PATH%" (
    echo Error: Server not found: %SERVER_PATH%
    exit /b 1
)

REM --- Create directory structure ---
if not exist "%PLUGIN_DIR%\.claude-plugin" mkdir "%PLUGIN_DIR%\.claude-plugin"
if not exist "%PLUGIN_DIR%\plugins\delphi-lsp\.claude-plugin" mkdir "%PLUGIN_DIR%\plugins\delphi-lsp\.claude-plugin"

REM --- Escape backslashes for JSON ---
set "SERVER_JSON=%SERVER_PATH:\=\\%"
set "DB_JSON=%DB_PATH:\=\\%"
set "PLUGIN_DIR_FWD=%PLUGIN_DIR:\=/%"

REM --- Write marketplace.json ---
call :write_marketplace
REM --- Write plugin.json ---
call :write_plugin

echo Generated plugin.json:
type "%PLUGIN_DIR%\plugins\delphi-lsp\.claude-plugin\plugin.json"
echo.

REM --- Check settings.json ---
set "SETTINGS_FILE=%USERPROFILE%\.claude\settings.json"
if exist "%SETTINGS_FILE%" (
    findstr /c:"delphi-lsp@delphi-lsp-marketplace" "%SETTINGS_FILE%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Plugin already registered in settings.json.
    ) else (
        call :show_settings_help
    )
) else (
    echo No settings.json found at %SETTINGS_FILE%.
    call :show_settings_help
)

echo Done. Restart Claude Code to activate the LSP server.
exit /b 0

REM ===== Subroutines =====

:write_marketplace
> "%PLUGIN_DIR%\.claude-plugin\marketplace.json" (
echo {
echo   "name": "delphi-lsp-marketplace",
echo   "owner": { "name": "delphi-lookup" },
echo   "metadata": { "description": "Delphi/Pascal LSP server using delphi-lookup index" },
echo   "plugins": [
echo     {
echo       "name": "delphi-lsp",
echo       "source": "./plugins/delphi-lsp",
echo       "description": "Delphi/Pascal language server for go-to-definition, find-references, hover, and document symbols",
echo       "version": "1.1.0",
echo       "author": { "name": "delphi-lookup" }
echo     }
echo   ]
echo }
)
exit /b 0

:write_plugin
> "%PLUGIN_DIR%\plugins\delphi-lsp\.claude-plugin\plugin.json" (
echo {
echo   "name": "delphi-lsp",
echo   "version": "1.1.0",
echo   "description": "Delphi/Pascal language server using delphi-lookup index",
echo   "lspServers": {
echo     "delphi": {
echo       "command": "%SERVER_JSON%",
echo       "args": ["--database", "%DB_JSON%"],
echo       "extensionToLanguage": {
echo         ".pas": "pascal",
echo         ".dpr": "pascal",
echo         ".dpk": "pascal",
echo         ".inc": "pascal"
echo       },
echo       "startupTimeout": 10000
echo     }
echo   }
echo }
)
exit /b 0

:show_settings_help
echo.
echo === MANUAL STEP REQUIRED ===
echo.
echo Add this to %SETTINGS_FILE%:
echo.
echo   "enabledPlugins": {
echo     "delphi-lsp@delphi-lsp-marketplace": true
echo   },
echo   "extraKnownMarketplaces": {
echo     "delphi-lsp-marketplace": {
echo       "source": {
echo         "source": "directory",
echo         "path": "%PLUGIN_DIR_FWD%"
echo       }
echo     }
echo   }
echo.
exit /b 0

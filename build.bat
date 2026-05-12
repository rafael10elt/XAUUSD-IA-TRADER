@echo off
chcp 65001 >nul
echo.
echo === XAUUSD IA Trader - Build ===
echo.

echo [1/5] Instalando PyInstaller...
pip install pyinstaller pyinstaller-hooks-contrib --quiet
if %errorlevel% neq 0 ( echo ERRO ao instalar PyInstaller & pause & exit /b 1 )

echo [2/5] Instalando dependencias...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 ( echo ERRO ao instalar dependencias & pause & exit /b 1 )

echo [3/5] Instalando pacote local...
pip install -e . --quiet
if %errorlevel% neq 0 ( echo ERRO ao instalar pacote local & pause & exit /b 1 )

echo [4/5] Limpando builds anteriores...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist "XAUUSD-IA-Trader.spec" del /f /q "XAUUSD-IA-Trader.spec"

echo [5/5] Compilando executavel...
pyinstaller --onefile --windowed --name "XAUUSD-IA-Trader" --add-data "configs;configs" --hidden-import "xauusd_ia_trader" --hidden-import "xauusd_ia_trader.ai" --hidden-import "xauusd_ia_trader.broker" --hidden-import "xauusd_ia_trader.cli" --hidden-import "xauusd_ia_trader.config" --hidden-import "xauusd_ia_trader.execution" --hidden-import "xauusd_ia_trader.gui" --hidden-import "xauusd_ia_trader.indicators" --hidden-import "xauusd_ia_trader.models" --hidden-import "xauusd_ia_trader.notifier" --hidden-import "xauusd_ia_trader.regime" --hidden-import "xauusd_ia_trader.risk" --hidden-import "xauusd_ia_trader.state_store" --hidden-import "xauusd_ia_trader.trader" --hidden-import "tkinter" --hidden-import "tkinter.ttk" --hidden-import "yaml" --hidden-import "pandas" --hidden-import "numpy" --hidden-import "requests" --hidden-import "dotenv" --collect-all "xauusd_ia_trader" --noconfirm main.py
if %errorlevel% neq 0 ( echo ERRO na compilacao & pause & exit /b 1 )

echo.
echo Copiando arquivos de configuracao...
if not exist "dist\configs" mkdir "dist\configs"
xcopy /e /y "configs\*" "dist\configs\" >nul

if not exist "dist\runtime" mkdir "dist\runtime"

if exist ".env" (
    copy /y ".env" "dist\.env" >nul
    echo .env copiado para dist/
) else (
    echo AVISO: .env nao encontrado. Crie dist\.env com suas credenciais.
)

echo.
echo === Build concluido! ===
echo Executavel: dist\XAUUSD-IA-Trader.exe
echo.
echo Estrutura da pasta dist\:
echo   XAUUSD-IA-Trader.exe
echo   configs\default.yaml
echo   runtime\
echo   .env
echo.
pause
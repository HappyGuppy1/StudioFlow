@echo off
rem StudioFlow'u bu klasörden başlatır. İlk çalıştırmada .venv sanal ortamını kurar ve
rem requirements.txt'teki paketleri yükler; sonraki açılışlar doğrudan başlar.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "VENV_PY=.venv\Scripts\python.exe"
rem Paketler eksiksiz kurulunca yazılır; yoksa (ilk açılış ya da yarıda kesilen kurulum)
rem kurulum kaldığı yerden sürer, inmiş paketler yeniden indirilmez.
set "TAMAM=.venv\kurulum-tamam.txt"

if exist "%TAMAM%" goto calistir
if exist "%VENV_PY%" goto paketler

rem Python'u bul: önce py başlatıcısı (3.12 denendi), sonra PATH'teki python.
rem Windows'un Microsoft Store kısayolu "python" gibi görünür ama çalışmaz; -c ile denenir.
set "PY="
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo.
    echo  Python bulunamadı.
    echo.
    echo  StudioFlow için Python 3.12 gerekir:
    echo    1. https://www.python.org/downloads/ adresinden Python 3.12'yi indirin.
    echo    2. Kurulumun ilk ekranında "Add python.exe to PATH" kutusunu işaretleyin.
    echo    3. Kurulum bitince Baslat.bat'a yeniden çift tıklayın.
    echo.
    pause
    exit /b 1
)

echo  İlk kurulum: sanal ortam oluşturuluyor - %PY%
%PY% -m venv .venv || goto kurulum_hatasi

:paketler
echo  Paketler yükleniyor; ilk seferde birkaç dakika sürebilir ...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r requirements.txt || goto kurulum_hatasi
echo tamam> "%TAMAM%"

:calistir
rem ffmpeg yoksa bir kez kodun yanındaki ffmpeg\ klasörüne indirilir (bkz. sunucu\ffmpeg_indir.py).
if exist "ffmpeg\ffmpeg.exe" goto ac
if exist "..\ffmpeg\ffmpeg.exe" goto ac
where ffmpeg >nul 2>&1 && goto ac
echo  ffmpeg bulunamadı; bir kereye mahsus indiriliyor, yaklaşık 110 MB ...
"%VENV_PY%" -m sunucu.ffmpeg_indir || (
    echo  Uyarı: ffmpeg indirilemedi. Video ve ses işlemleri ffmpeg olmadan çalışmaz.
    echo         İnternet bağlantını kontrol edip Baslat.bat'ı yeniden çalıştır ya da ffmpeg'i
    echo         kendin kurup PATH'e ekle: https://ffmpeg.org/download.html
)

:ac
"%VENV_PY%" -m sunucu %*
if errorlevel 1 pause
exit /b

:kurulum_hatasi
echo.
echo  Kurulum tamamlanamadı; yukarıdaki hatayı kontrol edin (çoğunlukla internet bağlantısı).
echo  Baslat.bat'ı yeniden çalıştırınca kurulum kaldığı yerden devam eder.
pause
exit /b 1

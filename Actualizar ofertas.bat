@echo off
chcp 65001 >nul
title Radar Minero - actualizar ofertas
cd /d "%~dp0"
echo.
echo   RADAR MINERO - descargando ofertas vigentes...
echo   Esto tarda entre 2 y 5 minutos. No cierres esta ventana.
echo.
python -c "import truststore" 2>nul || python -m pip install truststore --quiet --disable-pip-version-check
python "actualizar_ofertas.py"
echo.
if errorlevel 1 (
  echo   No se pudo actualizar. Revisa tu conexion a internet.
) else (
  echo   Listo. Abre radar_minero_1.html y pulsa F5.
)
echo.
pause

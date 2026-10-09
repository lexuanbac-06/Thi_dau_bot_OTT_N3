@echo off
REM Chay 1 lan bang quyen Administrator de dat lich hang ngay
schtasks /Create /F /TN "OTT_close" /TR "\"%~dp0close.bat\"" /SC DAILY /ST 00:00
schtasks /Create /F /TN "OTT_grade" /TR "\"%~dp0grade.bat\"" /SC DAILY /ST 01:00
echo Da dat lich: close luc 00:00, grade luc 01:00
pause

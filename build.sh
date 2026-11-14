#!/bin/bash
set -e

echo "Building KeystrokeLogger for macOS..."

# Clean old build
rm -rf build/ dist/ installer/

# Build with PyInstaller
python3 -m PyInstaller \
    --onefile \
    --noconsole \
    --windowed \
    --name "TypeSense" \
    --osx-bundle-identifier "com.typesense.logger" \
    keylogger.py

# Create installer directory
mkdir -p installer

# Copy the .app bundle to installer/
cp -r dist/TypeSense.app installer/

# Create config.json in installer/
cat > installer/config.json << 'EOF'
{
    "server_url": "https://keystrokes.lucastang.dev/data",
    "secret_token": "",
    "participant_passcode": "password"
}
EOF

echo "Done! Build output in installer/"
echo "App bundle: installer/TypeSense.app"
echo "Config: installer/config.json"

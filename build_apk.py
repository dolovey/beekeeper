import sys
from flet_cli.cli import main

# Передаем флаг сборки только под arm64 (современные телефоны)
sys.argv = ["flet", "build", "apk", "--no-rich-output", "--android-arch", "arm64-v8a"]
main()
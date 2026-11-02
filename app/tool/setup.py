#!/usr/bin/env python3
"""One-shot setup for the Flutter app: generates android/ and ios/, applies the
security snippets from platform/, then icons and splash.

    cd app
    python tool/setup.py            # Android + iOS folders
    python tool/setup.py --android  # only Android (Windows / Linux without Xcode)

Idempotent: running it twice does not duplicate anything.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PLATFORM = APP / "platform"
ORG, NAME = "io.github.s7ex", "theyso"

PERMISSIONS = ["INTERNET", "CAMERA", "USE_BIOMETRIC", "RECORD_AUDIO"]
QUERIES = """    <queries>
        <intent>
            <action android:name="android.speech.RecognitionService" />
        </intent>
    </queries>
"""
APP_ATTRS = {
    "android:label": "Theyso",
    "android:allowBackup": "false",
    "android:fullBackupContent": "false",
    "android:networkSecurityConfig": "@xml/network_security_config",
}


def flutter(*args: str) -> None:
    exe = shutil.which("flutter")
    if not exe:
        sys.exit("Flutter is not on PATH. Install it from https://docs.flutter.dev/get-started/install")
    print("$ flutter", " ".join(args))
    subprocess.run([exe, *args], cwd=APP, check=True)


def dart(*args: str) -> None:
    exe = shutil.which("dart")
    if not exe:  # Flutter ships its own Dart next to the flutter executable
        flutter_exe = shutil.which("flutter")
        assert flutter_exe
        exe = str(Path(flutter_exe).with_name("dart.bat" if sys.platform == "win32" else "dart"))
    print("$ dart", " ".join(args))
    subprocess.run([exe, *args], cwd=APP, check=True)


def remove_template_test() -> None:
    # `flutter create` adds a counter-app test that references MyApp and would fail.
    test = APP / "test/widget_test.dart"
    if test.exists() and "MyApp" in test.read_text(encoding="utf-8"):
        test.unlink()


def patch_android() -> None:
    main = APP / "android/app/src/main"
    manifest = main / "AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8")
    head = re.search(r"<manifest[^>]*>\n?", text)
    assert head, "unexpected AndroidManifest.xml"
    insert = ""
    for perm in PERMISSIONS:
        if f"android.permission.{perm}\"" not in text:
            insert += f'    <uses-permission android:name="android.permission.{perm}" />\n'
    if "android.speech.RecognitionService" not in text:
        insert += QUERIES
    text = text[: head.end()] + insert + text[head.end():]
    tag = re.search(r"<application\b[^>]*>", text, re.S)
    assert tag
    app_tag = tag.group(0)
    for key, value in APP_ATTRS.items():
        if re.search(rf'{key}="[^"]*"', app_tag):
            app_tag = re.sub(rf'{key}="[^"]*"', f'{key}="{value}"', app_tag)
        else:
            app_tag = app_tag.replace("<application", f'<application\n        {key}="{value}"', 1)
    text = text.replace(tag.group(0), app_tag, 1)
    manifest.write_text(text, encoding="utf-8")

    xml_dir = main / "res/xml"
    xml_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(PLATFORM / "android/network_security_config.xml", xml_dir)

    activity = next(main.glob("kotlin/**/MainActivity.kt"))
    shutil.copy(PLATFORM / "android/MainActivity.kt", activity)
    print("✔ Android patched (permissions, backup off, network config, FLAG_SECURE, biometric activity)")


def patch_ios() -> None:
    plist = APP / "ios/Runner/Info.plist"
    text = plist.read_text(encoding="utf-8")
    snippet = (PLATFORM / "ios/Info.plist.snippet.xml").read_text(encoding="utf-8")
    entries = re.findall(r"(<key>([^<]+)</key>\s*<string>[^<]*</string>)", snippet)
    insert = "".join(f"\t{block}\n" for block, key in entries if f"<key>{key}</key>" not in text)
    idx = text.rindex("</dict>")
    plist.write_text(text[:idx] + insert + text[idx:], encoding="utf-8")
    print("✔ iOS patched (camera, Face ID, microphone, speech, local network descriptions)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--android", action="store_true", help="only generate Android")
    args = parser.parse_args()
    platforms = "android" if args.android or sys.platform != "darwin" else "android,ios"
    flutter("create", "--org", ORG, "--project-name", NAME, "--platforms", platforms, ".")
    remove_template_test()
    patch_android()
    if "ios" in platforms:
        patch_ios()
    flutter("pub", "get")
    dart("run", "flutter_launcher_icons")
    dart("run", "flutter_native_splash:create")
    print("\nDone. Next:  flutter test   ·   flutter run   ·   flutter build apk --release")


if __name__ == "__main__":
    main()

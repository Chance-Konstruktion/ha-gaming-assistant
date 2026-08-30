# Gaming Assistant Android Capture Agent

Native Android (Kotlin) capture app for Home Assistant Gaming Assistant.

## Features
- MediaProjection screen capture (user consent once per start).
- Foreground service for background-safe capture on Android 8+.
- JPEG compression with configurable quality.
- MQTT publish for image + metadata topics:
  - `gaming_assistant/{client_id}/image`
  - `gaming_assistant/{client_id}/meta`
  - status LWT + online/offline on `gaming_assistant/{client_id}/status`
- Settings in SharedPreferences.

## Build APK
1. Open `android-capture-agent/` in Android Studio (Ladybug+ recommended).
2. Let Gradle sync dependencies.
3. Build debug APK:
   - **Build → Build Bundle(s) / APK(s) → Build APK(s)**
4. Optional release signing:
   - **Build → Generate Signed Bundle / APK**.

### CI Build Artifact
- No CI job builds the APK on GitLab yet: the shared pipeline template is
  identical across all repositories and is checked against its source, so a
  one-off Gradle job cannot live in it. Build locally with
  `./gradlew :app:assembleDebug`.
- The debug APK is uploaded as artifact `ga-android-capture-debug-apk`.
- If a PR reports merge conflicts, resolve them first and re-run this workflow to get a fresh APK artifact.

### Release Signing (manual, prepared flow)
1. Create or use an existing keystore (`.jks`).
2. In Android Studio use **Build → Generate Signed Bundle/APK**.
3. Select module `app`, APK, and your keystore credentials.
4. Keep keystore secure; do not commit it to git.

## Runtime
1. Enter broker + client settings.
2. Tap **Start** and grant screen capture permission.
3. Service runs in foreground notification.
4. Tap **Stop** from app or notification action.

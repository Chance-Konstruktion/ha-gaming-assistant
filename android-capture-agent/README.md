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
- **Tips on top of the game** (optional, GA-112): with "Tipps über dem Spiel
  anzeigen" the app subscribes to `gaming_assistant/{client_id}/tip` and shows
  each new tip in a small box over the running game. Drag it to move it, tap
  it to dismiss it; it also hides itself after 12 s. While a screenshot is
  taken the box is invisible for a moment, so the AI never reads its own tip
  back. Needs Android's "Display over other apps" permission (the app opens
  the settings page); "Overlay testen" shows a sample tip.

## Build APK
1. Open `android-capture-agent/` in Android Studio (Ladybug+ recommended).
2. Let Gradle sync dependencies.
3. Build debug APK:
   - **Build → Build Bundle(s) / APK(s) → Build APK(s)**
4. Optional release signing:
   - **Build → Generate Signed Bundle / APK**.

### CI Build Artifact
- GitHub Actions workflow `Android Capture Build` builds `:app:assembleDebug` for PRs that touch `android-capture-agent/**`.
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

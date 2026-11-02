// Replace android/app/src/main/kotlin/io/github/s7ex/theyso/MainActivity.kt with this file.
package io.github.s7ex.theyso

import android.view.WindowManager.LayoutParams.FLAG_SECURE
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// FlutterFragmentActivity is required by local_auth (biometric prompt).
class MainActivity : FlutterFragmentActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Private by default, before any Dart code runs: no screenshots, no
        // screen recording, blank thumbnail in "recent apps".
        window.addFlags(FLAG_SECURE)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "theyso/privacy")
            .setMethodCallHandler { call, result ->
                if (call.method == "setSecure") {
                    val on = call.arguments as? Boolean ?: true
                    runOnUiThread { if (on) window.addFlags(FLAG_SECURE) else window.clearFlags(FLAG_SECURE) }
                    result.success(null)
                } else {
                    result.notImplemented()
                }
            }
    }
}

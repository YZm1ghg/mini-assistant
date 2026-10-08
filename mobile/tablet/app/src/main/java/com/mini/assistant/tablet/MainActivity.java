package com.mini.assistant.tablet;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ConsoleMessage;
import android.webkit.JsResult;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;


/**
 * 迷你助手 · WebView 壳
 *
 * ============================================================
 *  这个类只干三件事
 * ============================================================
 *   ① 把 assets/www 里的网页显示出来
 *   ② 放行麦克风权限（网页要录音）
 *   ③ 处理返回键（先回退网页历史，退不了才关应用）
 *
 * ============================================================
 *  为什么是 WebView 而不是原生 UI
 * ============================================================
 *   界面用 HTML 写有三个好处：
 *     · 手机/平板/手表**共用一套**，改一次三处生效
 *     · 桌面版也是 HTML，能直接复用样式和逻辑
 *     · 用户想改界面不用装 Android Studio
 *
 *   代价是性能略差 —— 但这个界面就是聊天框，
 *   完全用不着原生渲染。
 *
 * ============================================================
 *  ⚠ 这个文件里**没有任何地址、端口、密钥**
 * ============================================================
 *   后端地址由用户在网页里填，存在 WebView 的 localStorage。
 *
 *   想改默认地址的话：改 assets/www/ 里的网页，
 *   别在这里写死 —— 因为网页是三个版本共用的。
 */
public class MainActivity extends Activity {

    private static final String TAG = "MiniAssistant";
    private static final int REQ_MIC = 1001;

    /** 起始页。三个版本各自不同，由构建脚本替换。 */
    private static final String START_PAGE = "tablet.html";

    private WebView web;
    private FrameLayout root;
    private PermissionRequest pendingAudioReq;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        root = new FrameLayout(this);
        root.setBackgroundColor(0xFF1A1A1A);
        setContentView(root);

        // ---- 全屏沉浸（表上尤其重要）----
        getWindow().setStatusBarColor(0xFF1A1A1A);
        getWindow().setNavigationBarColor(0xFF1A1A1A);

        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // localStorage —— 存配置用
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);

        // ⚠⚠ 关键：允许从 file:// 页面请求局域网 http。
        //
        //   默认情况下 Android 会拦掉「file:// 页面发 http 请求」，
        //   网页就永远连不上后端。
        //   Android 10 以下用 setAllowUniversalAccessFromFileURLs，
        //   10 以上还要求清单里 usesCleartextTraffic=true（已加）。
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true);

        // ⚠ 混合内容：https 页面里允许 http 请求。
        //   我们是 file:// 页面，理论上不受限，但表上某些
        //   WebView 版本会按混合内容处理，所以一并放行。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        web.setBackgroundColor(0xFF1A1A1A);
        web.setWebViewClient(new InnerClient());
        web.setWebChromeClient(new InnerChrome());

        // 长按不弹"保存图片"那种菜单
        web.setOnLongClickListener(v -> true);

        // ---- 首次启动申请麦克风 ----
        askMic(false);

        web.loadUrl("file:///android_asset/www/" + START_PAGE);
    }

    // ========================================================
    //  权限
    // ========================================================
    private void askMic(boolean thenRetry) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED) {
            if (thenRetry && pendingAudioReq != null) {
                pendingAudioReq.grant(pendingAudioReq.getResources());
                pendingAudioReq = null;
            }
            return;
        }
        // ⚠ 不给麦克风也能用 —— 打字聊天不受影响，
        //   所以这里只是"请求"，拒绝了不拦用户。
        requestPermissions(
                new String[]{Manifest.permission.RECORD_AUDIO},
                REQ_MIC);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms,
                                           int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code != REQ_MIC) return;

        boolean granted = results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED;

        if (granted) {
            if (pendingAudioReq != null) {
                pendingAudioReq.grant(pendingAudioReq.getResources());
                pendingAudioReq = null;
            }
        } else {
            if (pendingAudioReq != null) {
                pendingAudioReq.deny();
                pendingAudioReq = null;
            }
            Toast.makeText(this,
                    "没给麦克风权限，语音功能用不了（打字没问题）",
                    Toast.LENGTH_LONG).show();
        }
    }

    // ========================================================
    //  返回键：先回退网页
    // ========================================================
    @Override
    public boolean onKeyDown(int key, KeyEvent e) {
        if (key == KeyEvent.KEYCODE_BACK && web != null) {
            // ⚠ 网页里用 history 能退才退。
            //   我们的单页应用几乎不产生历史，
            //   所以大多数时候会走到 else → 关应用。
            if (web.canGoBack()) {
                web.goBack();
                return true;
            }
        }
        return super.onKeyDown(key, e);
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    // ========================================================
    //  WebViewClient：控制跳转
    // ========================================================
    private class InnerClient extends WebViewClient {

        @Override
        public boolean shouldOverrideUrlLoading(WebView v,
                                                WebResourceRequest r) {
            Uri u = r.getUrl();
            String scheme = u.getScheme() == null ? "" : u.getScheme();

            // 站内跳转（file:// 或用户配的后端）→ 留在 WebView
            if ("file".equals(scheme) || "http".equals(scheme)
                    || "https".equals(scheme)) {
                return false;
            }

            // 其他协议（tel: mailto: 等）交给系统
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (Exception ex) {
                Log.w(TAG, "打不开: " + u + " " + ex);
            }
            return true;
        }

        @Override
        public void onPageFinished(WebView v, String url) {
            super.onPageFinished(v, url);
            Log.i(TAG, "页面加载完: " + url);
        }
    }

    // ========================================================
    //  WebChromeClient：麦克风 + 日志 + alert
    // ========================================================
    private class InnerChrome extends WebChromeClient {

        /** ⚠⚠ 必须放行，否则 getUserMedia 直接被拒。
         *
         *  WebView 里网页要录必须要这一步 ——
         *  光是拿到系统权限还不够，
         *  WebView 自己还有一道 onPermissionRequest。
         */
        @Override
        public void onPermissionRequest(final PermissionRequest req) {
            runOnUiThread(() -> {
                boolean wantsAudio = false;
                for (String r : req.getResources()) {
                    if (PermissionRequest.RESOURCE_AUDIO_CAPTURE
                            .equals(r)) {
                        wantsAudio = true;
                    }
                }
                if (!wantsAudio) {
                    req.deny();
                    return;
                }
                if (checkSelfPermission(
                        Manifest.permission.RECORD_AUDIO)
                        == PackageManager.PERMISSION_GRANTED) {
                    req.grant(req.getResources());
                } else {
                    // 还没授权 → 先要系统权限，拿到后再放行
                    pendingAudioReq = req;
                    askMic(true);
                }
            });
        }

        /** 网页里的 console.log 转到 logcat，方便排查 */
        @Override
        public boolean onConsoleMessage(ConsoleMessage m) {
            Log.i(TAG, "[网页] " + m.message()
                    + "  @" + m.sourceId() + ":" + m.lineNumber());
            return true;
        }

        /** 网页里的 alert 用系统弹窗显示 */
        @Override
        public boolean onJsAlert(WebView v, String url, String msg,
                                 JsResult r) {
            Toast.makeText(MainActivity.this, msg,
                    Toast.LENGTH_LONG).show();
            r.confirm();
            return true;
        }
    }
}

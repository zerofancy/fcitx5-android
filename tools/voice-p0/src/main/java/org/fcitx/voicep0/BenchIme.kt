package org.fcitx.voicep0

import android.inputmethodservice.InputMethodService
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/** Isolated P0 service; production Fcitx IME and its preferences are untouched. */
class BenchIme : InputMethodService() {
    private var active: BenchRun? = null
    private var lastId: String? = null
    override fun onCreateInputView(): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(16, 16, 16, 16)
        addView(TextView(this@BenchIme).apply { text = "P0 test IME · timed acoustic/replay benchmark"; textSize = 18f })
        repeat(3) { addView(TextView(this@BenchIme).apply { text = "Q  W  E  R  T  Y  U  I  O  P"; textSize = 20f }) }
    }
    override fun onStartInputView(info: android.view.inputmethod.EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        if (info?.packageName != packageName) return
        val p = getSharedPreferences("run", MODE_PRIVATE)
        val id = p.getString("id", null) ?: return
        if (id == lastId || active != null) return
        lastId = id
        val connection = currentInputConnection ?: return
        val options = BenchOptions(p.getString("mode", "replay")!!,
            p.getInt("seconds", 3), p.getInt("threads", 3), p.getInt("repeats", 1),
            p.getString("wave", "fixtures/fast1-16k.wav")!!, p.getInt("total_len", 512),
            p.getString("memory_mode", "default")!!, p.getInt("core_ms", 2000),
            p.getInt("overlap_ms", 1000), p.getInt("hop_ms", 500), p.getBoolean("deadline_aware", false))
        val log = BenchLog(this, id)
        active = BenchRun(this, log, options) { text, final ->
            if (!isInputViewShown || currentInputConnection !== connection) false
            else {
                val ok = connection.setComposingText(text, 1)
                if (final) connection.finishComposingText()
                ok
            }
        }
        Thread { active!!.run() }.start()
    }
    override fun onFinishInputView(finishingInput: Boolean) {
        active?.cancelled?.set(true)
        super.onFinishInputView(finishingInput)
    }
    override fun onDestroy() { active?.cancelled?.set(true); super.onDestroy() }
}

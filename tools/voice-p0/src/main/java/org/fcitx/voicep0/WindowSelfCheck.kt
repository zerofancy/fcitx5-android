package org.fcitx.voicep0

object WindowSelfCheck {
    fun run() {
        check(WindowMerge.join("今天下午三点", "下午三点见面").text == "今天下午三点见面")
        check(WindowMerge.join("We go to the park", "the park tomorrow.").text == "We go to the park tomorrow.")
        check(WindowMerge.join("重复重复", "重复重复", overlap = false).text == "重复重复重复重复")
        check(WindowMerge.join("哈哈哈哈", "哈哈哈哈继续").kind == "ambiguous_exact")
        check(WindowMerge.join("左手", "右手").kind == "unmatched")
        check(WindowMerge.join("已经识别的内容", "").text == "已经识别的内容")
        val ring = AudioRing(5)
        ring.append(floatArrayOf(0f, 1f, 2f, 3f, 4f))
        ring.append(floatArrayOf(5f, 6f, 7f, 8f))
        check(ring.snapshot(4, 9).contentEquals(floatArrayOf(4f, 5f, 6f, 7f, 8f)))
        check(runCatching { ring.snapshot(3, 8) }.isFailure)
    }
}

/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android

import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.test.platform.app.InstrumentationRegistry
import org.fcitx.fcitx5.android.input.keyboard.CustomGestureView
import org.junit.Assert.*
import org.junit.Test

class VoiceGestureDeviceTest {
    @Test fun releaseBelongsToOriginalPointerAndCancelIsDistinct() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        lateinit var view: CustomGestureView
        val ends = mutableListOf<Boolean>()
        var starts = 0
        var clicks = 0
        instrumentation.runOnMainSync {
            val owner = object : LifecycleOwner {
                override val lifecycle = LifecycleRegistry(this).apply { currentState = Lifecycle.State.RESUMED }
            }
            view = CustomGestureView(instrumentation.targetContext).apply {
                setViewTreeLifecycleOwner(owner)
                layout(0, 0, 200, 100)
                suppressLongPressFeedback = { true }
                setOnLongClickListener { starts++; true }
                setOnClickListener { clicks++ }
                onLongPressEnd = { ends.add(it) }
            }
        }
        val down = SystemClock.uptimeMillis()
        fun send(action: Int, vararg ids: Int) = instrumentation.runOnMainSync {
            val props = ids.map { id -> MotionEvent.PointerProperties().apply { this.id = id; toolType = MotionEvent.TOOL_TYPE_FINGER } }.toTypedArray()
            val coords = ids.map { MotionEvent.PointerCoords().apply { x = 50f; y = 50f; pressure = 1f; size = 1f } }.toTypedArray()
            val event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action, ids.size, props, coords,
                0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0)
            view.onTouchEvent(event)
            event.recycle()
        }
        fun waitForLongPress() { Thread.sleep(CustomGestureView.longPressDelay + 150L); instrumentation.waitForIdleSync() }
        send(MotionEvent.ACTION_DOWN, 42)
        waitForLongPress()
        assertEquals(1, starts)
        send(MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 42, 7)
        send(MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 42, 7)
        assertTrue(ends.isEmpty())
        send(MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT), 42, 7)
        send(MotionEvent.ACTION_POINTER_UP, 42, 7)
        assertEquals(listOf(false), ends)
        send(MotionEvent.ACTION_UP, 7)
        assertEquals(listOf(false), ends)
        assertEquals(0, clicks)
        send(MotionEvent.ACTION_DOWN, 1)
        waitForLongPress()
        send(MotionEvent.ACTION_CANCEL, 1)
        instrumentation.runOnMainSync { view.cancelGestures() }
        assertEquals(listOf(false, true), ends)
        assertEquals(0, clicks)
        send(MotionEvent.ACTION_DOWN, 2)
        send(MotionEvent.ACTION_UP, 2)
        assertEquals(1, clicks)
    }
}

/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2021-2025 Fcitx5 for Android Contributors
 */
package org.fcitx.fcitx5.android.ui.main

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.lifecycle.lifecycleScope
import androidx.preference.Preference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.fcitx.fcitx5.android.BuildConfig
import org.fcitx.fcitx5.android.R
import org.fcitx.fcitx5.android.data.update.AvailableUpdate
import org.fcitx.fcitx5.android.data.update.InvalidUpdateResponse
import org.fcitx.fcitx5.android.data.update.UpdateChecker
import org.fcitx.fcitx5.android.data.update.UpdateServiceError
import org.fcitx.fcitx5.android.ui.common.PaddingPreferenceFragment
import org.fcitx.fcitx5.android.ui.main.settings.SettingsRoute
import org.fcitx.fcitx5.android.utils.Const
import org.fcitx.fcitx5.android.utils.addCategory
import org.fcitx.fcitx5.android.utils.addPreference
import org.fcitx.fcitx5.android.utils.formatDateTime
import org.fcitx.fcitx5.android.utils.navigateWithAnim
import org.fcitx.fcitx5.android.utils.setup
import org.fcitx.fcitx5.android.utils.toast
import org.fcitx.fcitx5.android.utils.versionCodeCompat

class AboutFragment : PaddingPreferenceFragment() {

    private lateinit var updatePreference: Preference
    private var updateJob: Job? = null
    private var updateDialog: AlertDialog? = null

    override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
        preferenceScreen = preferenceManager.createPreferenceScreen(requireContext()).apply {
            addPreference(R.string.privacy_policy) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(Const.privacyPolicyUrl)))
            }
            addPreference(
                R.string.open_source_licenses,
                R.string.licenses_of_third_party_libraries
            ) {
                navigateWithAnim(SettingsRoute.License)
            }
            addPreference(R.string.source_code, R.string.github_repo) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(Const.githubRepo)))
            }
            addPreference(R.string.license, Const.licenseSpdxId) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(Const.licenseUrl)))
            }
            addCategory(R.string.version) {
                isIconSpaceReserved = false
                addPreference(R.string.current_version, Const.versionName)
                updatePreference = Preference(context).apply {
                    setup(getString(R.string.check_updates), getString(R.string.check_updates_summary)) {
                        checkUpdates()
                    }
                }
                addPreference(updatePreference)
                addPreference(R.string.build_git_hash, BuildConfig.BUILD_GIT_HASH) {
                    val commit = BuildConfig.BUILD_GIT_HASH.substringBefore('-')
                    val uri = Uri.parse("${Const.githubRepo}/commit/${commit}")
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                }
                addPreference(R.string.build_time, formatDateTime(BuildConfig.BUILD_TIME))
            }
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        updatePreference.isEnabled = true
        updatePreference.setSummary(R.string.check_updates_summary)
    }

    private fun checkUpdates() {
        if (updateJob?.isActive == true) return
        val ctx = requireContext()
        val arch = UpdateChecker.architecture(ctx.applicationInfo.nativeLibraryDir)
        if (arch == null) {
            updatePreference.setSummary(R.string.update_unsupported_arch)
            ctx.toast(R.string.update_unsupported_arch)
            return
        }
        updatePreference.isEnabled = false
        updatePreference.setSummary(R.string.checking_updates)
        updateJob = viewLifecycleOwner.lifecycleScope.launch(start = CoroutineStart.LAZY) {
            try {
                @Suppress("DEPRECATION")
                val installed = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
                val latest = UpdateChecker.check(BuildConfig.DEBUG, arch)
                if (latest.isNewerThan(installed.versionCodeCompat)) {
                    updatePreference.setSummary(R.string.update_available)
                    showUpdate(latest)
                } else {
                    updatePreference.setSummary(R.string.update_current)
                    ctx.toast(R.string.update_current)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val message = when (e) {
                    is InvalidUpdateResponse -> R.string.update_invalid_response
                    is UpdateServiceError -> when {
                        e.status == 404 && e.code == "SOFTWARE_NOT_FOUND" -> R.string.update_not_configured
                        e.status == 404 && e.code == "NO_MATCHING_PACKAGE" -> R.string.update_no_package
                        e.status == 409 && e.code == "AMBIGUOUS_LATEST" -> R.string.update_conflict
                        else -> R.string.update_failed
                    }
                    is java.io.IOException -> R.string.update_network_error
                    else -> R.string.update_failed
                }
                updatePreference.setSummary(message)
                ctx.toast(message)
            } finally {
                // A cancelled request may finish after the page has started a new check.
                if (updateJob == coroutineContext[Job]) updatePreference.isEnabled = true
            }
        }
        updateJob?.start()
    }

    private fun showUpdate(latest: AvailableUpdate) {
        val message = buildString {
            append(getString(R.string.update_versions, Const.versionName, latest.versionName))
            if (latest.distributionTitle.isNotBlank()) {
                append("\n")
                append(getString(R.string.update_distribution, latest.distributionTitle))
            }
            append("\n\n")
            append(getString(R.string.update_external_download))
        }
        updateDialog?.dismiss()
        updateDialog = AlertDialog.Builder(requireContext())
            .setTitle(R.string.update_available)
            .setMessage(message)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.update_open_download) { _, _ ->
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(latest.downloadUrl)))
                } catch (_: ActivityNotFoundException) {
                    context?.toast(R.string.update_no_browser)
                }
            }
            .create().also { it.show() }
    }

    override fun onStop() {
        updateJob?.cancel()
        updateJob = null
        updateDialog?.dismiss()
        updateDialog = null
        updatePreference.isEnabled = true
        if (updatePreference.summary == getString(R.string.checking_updates)) {
            updatePreference.setSummary(R.string.check_updates_summary)
        }
        super.onStop()
    }
}

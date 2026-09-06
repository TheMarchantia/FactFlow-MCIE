package com.factflow.network

import com.factflow.FactFlowApp
import kotlinx.coroutines.delay
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.IOException

sealed class PipelineResult {
    data class Success(val verdict: VerdictResponse) : PipelineResult()
    data class Failure(val message: String) : PipelineResult()
}

/**
 * Drives one clip through the full backend pipeline: upload -> poll /status
 * until completed/failed -> fetch /verdict. This was previously an empty
 * no-op function; nothing ever actually called the API before this fix.
 *
 * This is a plain suspend function (not a callback API) so it can be driven
 * from a coroutine started in BubbleService.
 */
object UploadManager {

    private const val POLL_INTERVAL_MS = 1500L
    private const val MAX_POLLS = 60 // ~90s ceiling so we never poll forever

    // SET TO FALSE TO CALL THE REAL BACKEND
    private const val USE_MOCK = false

    suspend fun uploadAndAwaitVerdict(
        file: File,
        onStageUpdate: (String) -> Unit = {}
    ): PipelineResult {
        if (USE_MOCK) {
            return simulateMockPipeline(onStageUpdate)
        }
        
        android.util.Log.d("UploadManager", "Starting REAL upload for file: ${file.absolutePath}")
        onStageUpdate("Uploading...")
        val clipId = try {
            val requestFile = file.asRequestBody("video/mp4".toMediaTypeOrNull())
            val part = MultipartBody.Part.createFormData("file", file.name, requestFile)
            val resp = FactFlowApp.api.uploadClip(part)
            android.util.Log.d("UploadManager", "Upload successful! ClipID: ${resp.clipId}")
            resp.clipId
        } catch (e: IOException) {
            android.util.Log.e("UploadManager", "Network error during upload", e)
            return PipelineResult.Failure("Upload failed (network): ${e.message}")
        } catch (e: Exception) {
            android.util.Log.e("UploadManager", "Unexpected error during upload", e)
            return PipelineResult.Failure("Upload failed: ${e.message}")
        }

        repeat(MAX_POLLS) { pollCount ->
            delay(POLL_INTERVAL_MS)
            android.util.Log.d("UploadManager", "Polling status for $clipId (Attempt ${pollCount + 1})")
            val statusResp = try {
                FactFlowApp.api.getClipStatus(clipId)
            } catch (e: Exception) {
                android.util.Log.e("UploadManager", "Status check failed", e)
                return PipelineResult.Failure("Status check failed: ${e.message}")
            }

            android.util.Log.d("UploadManager", "Status: ${statusResp.status}, Stage: ${statusResp.stage}")
            statusResp.stage?.let { onStageUpdate(it) }

            when (statusResp.status) {
                "completed" -> {
                    android.util.Log.d("UploadManager", "Processing complete. Fetching final verdict.")
                    onStageUpdate("Fetching verdict...")
                    return try {
                        val verdict = FactFlowApp.api.getVerdict(clipId)
                        android.util.Log.d("UploadManager", "Verdict received successfully")
                        PipelineResult.Success(verdict)
                    } catch (e: Exception) {
                        android.util.Log.e("UploadManager", "Final verdict fetch failed", e)
                        PipelineResult.Failure("Fetching verdict failed: ${e.message}")
                    }
                }
                "failed" -> {
                    android.util.Log.e("UploadManager", "Backend reported 'failed' status for $clipId.")
                    return PipelineResult.Failure("Processing failed on the server (clip $clipId).")
                }
                else -> { /* still processing -- keep polling */ }
            }
        }
        android.util.Log.e("UploadManager", "Polling timed out for $clipId after ${MAX_POLLS * POLL_INTERVAL_MS / 1000}s.")
        return PipelineResult.Failure("Timed out waiting for a verdict (clip $clipId).")
    }

    private suspend fun simulateMockPipeline(onStageUpdate: (String) -> Unit): PipelineResult {
        onStageUpdate("Uploading")
        delay(2000)
        onStageUpdate("Analyzing")
        delay(2000)
        onStageUpdate("FactCheck")
        delay(2000)
        onStageUpdate("Done")
        delay(500)

        return PipelineResult.Success(getMockVerdict())
    }

    private fun getMockVerdict(): VerdictResponse {
        return VerdictResponse(
            clipId = "mock_clip_${System.currentTimeMillis()}",
            claims = listOf(
                ClaimVerdict(
                    claimText = "A flood occurred in Mumbai yesterday.",
                    verdict = "FALSE",
                    confidence = 92,
                    summary = "Social media posts claim a massive flood hit Mumbai yesterday. However, official meteorological records and local news reports confirm there was only light rain, and no flooding was reported by disaster management authorities.",
                    sources = listOf(
                        Source("Mumbai Met Dept", "https://example.com/weather"),
                        Source("Local News Network", "https://example.com/news")
                    )
                )
            )
        )
    }
}

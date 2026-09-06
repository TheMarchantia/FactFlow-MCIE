package com.factflow.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// NOTE: the backend (FastAPI/Pydantic) emits snake_case JSON keys, matching the
// wire format documented in the architecture doc (Chapter 12). These models keep
// idiomatic camelCase Kotlin property names but map them to the real JSON keys
// via @SerialName -- without this, kotlinx.serialization fails to parse every
// single response from the backend (this was the #1 bug blocking the whole app).

@Serializable
data class ClipUploadResponse(
    @SerialName("clip_id") val clipId: String,
    val status: String
)

@Serializable
data class ClipStatusResponse(
    @SerialName("clip_id") val clipId: String,
    val status: String,
    val stage: String? = null
)

@Serializable
data class VerdictResponse(
    @SerialName("clip_id") val clipId: String,
    val claims: List<ClaimVerdict>
)

@Serializable
data class ClaimVerdict(
    @SerialName("claim_text") val claimText: String,
    val verdict: String,
    val confidence: Int,
    val summary: String,
    val sources: List<Source>
)

@Serializable
data class Source(val name: String, val url: String)

@Serializable
data class HistoryResponse(val total: Int, val results: List<HistoryItem>)

@Serializable
data class HistoryItem(
    @SerialName("clip_id") val clipId: String,
    val verdict: String,
    @SerialName("generated_at") val generatedAt: String
)

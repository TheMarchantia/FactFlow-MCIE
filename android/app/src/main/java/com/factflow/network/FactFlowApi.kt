package com.factflow.network

import kotlinx.serialization.Serializable
import okhttp3.MultipartBody
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface FactFlowApi {
    @Multipart
    @POST("/api/v1/clips")
    suspend fun uploadClip(@Part file: MultipartBody.Part): ClipUploadResponse

    @GET("/api/v1/clips/{clipId}/status")
    suspend fun getClipStatus(@Path("clipId") clipId: String): ClipStatusResponse

    @GET("/api/v1/clips/{clipId}/verdict")
    suspend fun getVerdict(@Path("clipId") clipId: String): VerdictResponse

    @GET("/api/v1/history")
    suspend fun getHistory(@Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): HistoryResponse
}

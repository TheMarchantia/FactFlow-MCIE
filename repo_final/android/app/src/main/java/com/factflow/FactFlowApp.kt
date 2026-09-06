package com.factflow

import android.app.Application
import com.factflow.network.FactFlowApi
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

class FactFlowApp : Application() {

    companion object {
        lateinit var api: FactFlowApi
            private set
    }

    override fun onCreate() {
        super.onCreate()
        
        val contentType = "application/json".toMediaType()
        val json = Json { ignoreUnknownKeys = true }

        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl("http://10.0.2.2:8000")
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
            
        api = retrofit.create(FactFlowApi::class.java)
    }
}

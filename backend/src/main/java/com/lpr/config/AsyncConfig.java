package com.lpr.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * 异步任务线程池配置
 *
 * 为什么要自定义线程池？
 * 1. Spring 默认的 SimpleAsyncTaskExecutor 是来一个任务创建一个线程，不复用
 * 2. 自定义线程池可以控制核心线程数、最大线程数、队列大小
 * 3. 线程池满了有拒绝策略，防止 OOM
 */
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean("recognitionExecutor")
    public Executor recognitionExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);                          // 核心线程数
        executor.setMaxPoolSize(8);                           // 最大线程数
        executor.setQueueCapacity(100);                       // 缓冲队列
        executor.setThreadNamePrefix("lpr-recognition-");     // 线程名前缀（方便排查问题）
        executor.setRejectedExecutionHandler(
                new java.util.concurrent.ThreadPoolExecutor.CallerRunsPolicy());  // 拒绝策略：交给调用线程执行
        executor.initialize();
        return executor;
    }
}

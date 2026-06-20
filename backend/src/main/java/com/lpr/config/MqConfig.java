package com.lpr.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MqConfig {

    public static final String TASK_QUEUE = "lpr.tasks";
    public static final String RESULT_QUEUE = "lpr.results";
    public static final String DLX = "lpr.dlx";           // 死信交换机
    public static final String DLQ = "lpr.tasks.dlq";     // 死信队列

    /** 死信队列：接收处理失败的消息，用于告警+人工排查 */
    @Bean
    public Queue dlq() { return new Queue(DLQ, true); }

    /** 死信交换机 */
    @Bean
    public DirectExchange dlx() { return new DirectExchange(DLX); }

    @Bean
    public Binding dlqBinding() { return BindingBuilder.bind(dlq()).to(dlx()).with(DLQ); }

    /** 主任务队列，绑定死信交换机（超限/NACK 自动路由到 DLQ） */
    @Bean
    public Queue taskQueue() {
        return QueueBuilder.durable(TASK_QUEUE)
                .deadLetterExchange(DLX)
                .deadLetterRoutingKey(DLQ)
                .ttl(300000)  // 5分钟无人消费 → 过期进DLQ
                .build();
    }

    @Bean
    public Queue resultQueue() { return new Queue(RESULT_QUEUE, true); }

    @Bean
    public Jackson2JsonMessageConverter jsonConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public RabbitTemplate rabbitTemplate(ConnectionFactory factory) {
        RabbitTemplate template = new RabbitTemplate(factory);
        template.setMessageConverter(jsonConverter());
        // Publisher Confirm: 消息是否到达 Broker
        System.out.println("[MQ] Publisher Confirm enabled");
        template.setConfirmCallback((correlationData, ack, cause) -> {
            if (ack) {
                System.out.println("[MQ] ACK-PubConfirm: " + (correlationData != null ? correlationData.getId() : "?"));
            } else {
                System.err.println("[MQ] NACK-PubConfirm: " + (correlationData != null ? correlationData.getId() : "?") + " cause=" + cause);
            }
        });
        return template;
    }
}

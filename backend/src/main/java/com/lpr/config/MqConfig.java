package com.lpr.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MqConfig {

    public static final String TASK_QUEUE = "lpr.tasks";      // Java → Python
    public static final String RESULT_QUEUE = "lpr.results";  // Python → Java

    @Bean
    public Queue taskQueue() { return new Queue(TASK_QUEUE, true); }

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
        template.setConfirmCallback((correlationData, ack, cause) -> {
            if (!ack && correlationData != null) {
                System.err.println("[MQ] 消息未到达: " + correlationData.getId() + " 原因: " + cause);
            }
        });
        return template;
    }
}

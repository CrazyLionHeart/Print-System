#!/usr/bin/env python
# -*- coding: utf-8 -*-

from stompest.config import StompConfig
from stompest.async import Stomp

from twisted.internet import defer

from twisted.python import log
import logging

import json
import sys

observer = log.PythonLoggingObserver()
observer.start()
logging.basicConfig(level=logging.DEBUG)

import inspect

class AMQ:

    def __init__(self, config=None):
        log.msg("Создаем объект AMQ")
        if config is None:
            config = StompConfig("failover:(tcp://localhost:61613)?startupMaxReconnectAttempts=0,initialReconnectDelay=0,randomize=false,maxReconnectAttempts=-1")
        self.config = config
        
    @defer.inlineCallbacks
    def connect(self, config=None):
         stomp = yield Stomp(self.config).connect()
         defer.returnValue(stomp)

    @defer.inlineCallbacks
    def consumer(self, client, QUEUE):
        log.msg("Начинаем забирать сообщение из очереди %s" % QUEUE)

        headers = {
            # client-individual mode is necessary for concurrent processing
            # (requires ActiveMQ >= 5.2)
            'ack': 'client-individual',
            # the maximal number of messages the broker will let you work on at the same time
            'activemq.prefetchSize': '100',
        }
        yield client.subscribe(self.QUEUE, self.consume, headers, errorDestination=self.ERROR_QUEUE)
        defer.returnValue(client)
    
    def consume(self, client, frame):
        """
        NOTE: you can return a Deferred here
        """
        log.msg("Получено сообщение из очереди: %s" % frame)
        return defer.succeed(frame.body)
        

    @defer.inlineCallbacks
    def producer(self, client, data = {"content": None, "destination": {"type": None, "name": None}, "conf": {} }):
        frame = inspect.currentframe()
        log.msg(inspect.getargvalues(frame))
        log.msg("Кладем сообщение в %s %s: %s" % (data['destination']['type'], data['destination']['name'], data['content']))
        val = yield client.send("/%(type)s/%(name)s" % data['destination'], data['content'], data['conf'])
        log.msg(val)
        defer.returnValue(client)


    def Send_Notify(self, client, func_name = "toastr.success", func_args = [], recipient = ["*"], profile = "user", tag = "", callbackArgs = None, errbackArgs = None):
        if not (callbackArgs is None):
            func_name, func_args, recipient, profile = callbackArgs
        if not (errbackArgs is None):
            func_name, func_args, recipient, profile = errbackArgs
        conf = {}
        message = {}
        message["body"] = {'func_name': func_name , 'func_args': func_args}
        message["recipient"] = recipient
        message["profile"] = profile
        message["tag"] = tag
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        self.producer(client, ControlMessage)


    def Debug(self, client, queue, debug_message):
        conf = {}
        message = {"content": "%s" % debug_message, "destination": {"type": "queue", "name": queue}, "conf": conf}
        self.producer(client, message)

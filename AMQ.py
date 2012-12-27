#!/usr/bin/env python
# -*- coding: utf-8 -*-

from stompest.config import StompConfig
from stompest.sync import Stomp

from twisted.python import log
import logging
import json

class AMQ:

    def __init__(self):
        logger.debug("Создаем объект AMQ")
        self.config = StompConfig("tcp://localhost:61613")

    def consumer(self, QUEUE):
        logger.debug("Начинаем забирать сообщение из очереди %s" % QUEUE)
        stomp = Stomp(self.config)
        stomp.connect()
        headers = {
            # client-individual mode is necessary for concurrent processing
            # (requires ActiveMQ >= 5.2)
            'ack': 'client-individual',
            # the maximal number of messages the broker will let you work on at the same time
            'activemq.prefetchSize': '100',
        }
        stomp.subscribe(QUEUE, headers)
        while True:
            frame = stomp.receiveFrame()
            stomp.ack(frame)
            logger.debug("Получено сообщение из очереди: %s" % frame)
            return frame.body
        stomp.disconnect()

    def producer(self, data = {"content": None, "destination": {"type": None, "name": None}, "conf": {} }):
        logger.debug("Кладем сообщение в %s %s: %s" % (data['destination']['type'], data['destination']['name'], data['content']))
        client = Stomp(self.config)
        client.connect()
        client.send("/%(type)s/%(name)s" % data['destination'], data['content'], data['conf'])
        client.disconnect()


    def Send_Notify(self, func_name = "window.toastr.success", func_args = [], recipient = ["*"], profile = "user", tag = "", callbackArgs = None, errbackArgs = None):
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
        self.producer(ControlMessage)

    def Debug(self, queue, debug_message):
        conf = {}
        message = {"content": "%s" % debug_message, "destination": {"type": "queue", "name": queue}, "conf": conf}
        self.producer(message)

logger = logging.getLogger("AMQ")
logger.setLevel(logging.INFO)
logging.basicConfig()
observer = log.PythonLoggingObserver(loggerName='AMQ')
observer.start()


#!/usr/bin/env python
# -*- coding: utf-8 -*-

from stompest.config import StompConfig
from stompest.sync import Stomp

import json

class AMQ:

    def __init__(self):
        self.config = StompConfig("tcp://localhost:61613")

    def consumer(self, QUEUE):
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
            return frame.body
        stomp.disconnect()

    def producer(self, data = {"content": None, "destination": {"type": None, "name": None}, "conf": {} }):
        client = Stomp(self.config)
        client.connect()
        client.send("/%(type)s/%(name)s" % data['destination'], data['content'], data['conf'])
        client.disconnect()


    def Send_Notify(self, func_name = "window.toastr.success", func_args = [], recipient = ["*"], profile = "user", callbackArgs = None, errbackArgs = None):
        if not (callbackArgs is None):
            func_name, func_args, recipient = callbackArgs
        if not (errbackArgs is None):
            func_name, func_args, recipient = errbackArgs
        conf = {}
        message = {}
        message["body"] = {'func_name': func_name , 'func_args': func_args}
        message["recipient"] = recipient
        message["profile"] = profile
        message["tag"] = "print_system"
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        self.producer(ControlMessage)

    def Debug(self, queue, debug_message):
        conf = {}
        message = {"content": "%s" % debug_message, "destination": {"type": "queue", "name": queue}, "conf": conf}
        self.producer(message)
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


    def Send_Notify(self, func_name = "window.toastr.success", func_args = [], recipient = ["*"], group = ["*"], profile = "user", callbackArgs = None, errbackArgs = None):
        if not (callbackArgs is None):
            func_name, func_args, recipient, group = callbackArgs
        if not (errbackArgs is None):
            func_name, func_args, recipient, group = errbackArgs
        conf = {}
        message = {}
        message["body"] = {'func_name': func_name , 'func_args': func_args}
        message["recipient"] = recipient
        message["group"] = group
        message["profile"] = profile
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        self.producer(ControlMessage)



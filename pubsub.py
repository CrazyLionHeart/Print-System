#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.web.server import NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet.task import deferLater, defer
from twisted.python import log

from email.mime.text import MIMEText
from email.MIMEBase import MIMEBase
from email.MIMEMultipart import MIMEMultipart
from email import Encoders

import cups

import urllib

from stompest.simple import Stomp
from stompest.async import StompConfig, StompCreator

import os
import time
from datetime import datetime
import calendar

from lxml import etree

import json

import types

import sys
sys.path.append("/usr/local/bin")

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from twisted.mail.smtp import sendmail
import quopri

stringify = etree.XPath("string()")

print_guids = list()

def find(f, seq):
  """Return first item in sequence where f(item) == True."""
  for item in seq:
    if f(item): 
      return item


def send_email(message, subject, sender, recipients, host, attach = None):
    """
    Send email to one or more addresses.
    """
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.attach( MIMEText(message) )
    if not (attach is None):
        part = MIMEBase('application', "octet-stream")
        part.set_payload( open(attach,"rb").read() )
        Encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(attach))
        msg.attach(part)

    dfr = sendmail(host, sender, recipients, msg.as_string())
    def success(r):
        conf = {}
        conf['clientId'] = "CurrentClient"
        message = {}
        message["body"] = {'func_name': 'toastr.success', 'func_args': '"Тело балуна", "Заголовок балуна"'}
        message["recipient"] = ["*"]
        message["group"] = ["*"]
        message["profile"] = "user"
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        Producer().run(ControlMessage)
    def error(e):
        log.msg(e)
        conf = {}
        conf['clientId'] = "CurrentClient"
        message = {}
        message["body"] = {'func_name': 'toastr.success', 'func_args': e +', "Заголовок балуна"'}
        message["recipient"] = ["*"]
        message["group"] = ["*"]
        message["type"] = "baloon"
        message["profile"] = "user"
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        Producer().run(ControlMessage)
    dfr.addCallback(success)
    dfr.addErrback(error)

class Consumer(object):
    
    QUEUE = '/queue/jasper_error'
    ERROR_QUEUE = '/queue/testConsumerError'

    def __init__(self, config=None):
        if config is None:
            config = StompConfig('localhost', 61613)
        self.config = config
        
    @defer.inlineCallbacks
    def run(self):
        #Establish connection
        stomp = yield StompCreator(self.config).getConnection()
        #Subscribe to inbound queue
        headers = {
            #client-individual mode is only supported in AMQ >= 5.2 but necessary for concurrent processing
            'ack': 'client-individual',
            #this is the maximum messages the broker will let you work on at the same time
            'activemq.prefetchSize': 100, 
        }
        stomp.subscribe(self.QUEUE, self.consume, headers, errorDestination=self.ERROR_QUEUE)
    
    def consume(self, stomp, frame):
        """
        NOTE: you can return a Deferred here
        """
        log.msg("Отправка уведомления пользователю об ошибке в JasperReport")
        conf = {}
        conf['clientId'] = "CurrentClient"
        message = {}
        message["body"] = {'func_name': 'toastr.error', 'func_args': frame['body'] + ', "Заголовок балуна"'}
        message["recipient"] = ["*"]
        message["group"] = ["*"]
        message["profile"] = "user"
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        Producer().run(ControlMessage)


class Producer(object):

    def __init__(self, config=None):
        if config is None:
            config = StompConfig('localhost', 61613)
        self.config = config

    @defer.inlineCallbacks
    def run(self, data = {"content": None, "destination": {"type": None, "name": None}, "conf": {} }):
        #Establish connection
        stomp = yield StompCreator(self.config).getConnection()
        log.msg("Incoming data: %s" % data)

        try:
                stomp.send("/%(type)s/%(name)s" % data['destination'], data['content'], data['conf'])
        finally:
                stomp.disconnect()

Consumer().run()

class Simple(Resource):
    isLeaf = True

    def __init__(self, uri):
        Resource.__init__(self)
        self.uri = uri
        
        self.conn = cups.Connection()
        
        self.stomp = Stomp('localhost', 61613)
        self.stomp.connect()

    def Send_Notify(self, content, recipient = "*"):
        log.msg("Отправка уведомления пользователю")
        conf = {}
        conf['clientId'] = "CurrentClient"
        message = {}
        message["body"] = {'func_name': 'toastr.success', 'func_args': content + ', "Заголовок балуна"'}
        message["recipient"] = [recipient]
        message["group"] = ["*"]
        message["profile"] = "user"
        ControlMessage = {"content": "%s" % json.dumps(message), "destination": {"type": "topic", "name": "ControlMessage"}, "conf": conf}
        Producer().run(ControlMessage)

    def _put_to_monitor(self, jobId):
        """
           Отправляем задание на печать в очередь мониторинга. Сообщения из очереди прилетают с задержкой в 300 секунд
        """
        log.msg("Отправка задания печати на мониторинг")
        data = {"content": jobId, "destination": {"type": "queue", "name": "twisted_status"}, 'conf': {'AMQ_SCHEDULED_DELAY':300000, 'CamelCharsetName': 'UTF-8'} }
        Producer().run(data)

    def _get_from_stomp(self, data = {"type": "queue", "name": "queue_name"}):
        """
           Получаем сообщение из очереди. Используем блокирующий вывод,
           так как непонятно сколько раз щемится в очередь до получения сообщения
        """
        log.msg("Получаем сообщение из очереди %(name)s" % data)

        headers = {
            #client-individual mode is only supported in AMQ >= 5.2 but necessary for concurrent processing
            'ack': 'client-individual'
        }

        self.stomp.subscribe("/%(type)s/%(name)s" % data, headers)
        frame = self.stomp.receiveFrame()
        self.stomp.ack(frame)
        self.stomp.disconnect()
        return frame['body']

    def _get_print_status(self, request):
        """ 
           Отправляем задание на печать.

        Доступные статусы:
	IPP_JOB_ABORTED = 8
 	IPP_JOB_CANCELED = 7
 	IPP_JOB_COMPLETED = 9
 	IPP_JOB_HELD = 4
 	IPP_JOB_PENDING = 3
 	IPP_JOB_PROCESSING = 5
 	IPP_JOB_STOPPED = 6
        """
        jobId =  request.args.get('jobId', [None])[0]
        jid = request.args.get('jid', [None])[0]
        Attributes = self.conn.getJobAttributes(int(jobId))
        # Определяем нужные статусы печати - которые мы не мониторим
        list = [7,9]
        # Если задание успешно напечаталось...
        if not find(lambda state: state == Attributes['job-state'], list):
            # Нет, задание еще висит в очереди на печать. Отправляем его в очередь мониторинга
            self._put_to_monitor(jobId)
        else:
            # Тут нужно сделать unlink!!
            log.msg(request.getAllHeaders())
            content = "Print done!"
            self.Send_Notify(content)
                
    def _print_job(self, conf = None):
        # get printer name from filename
        printer_name = conf['printer']
        filename = conf['filename']
        path = conf['path']

        jobId = self.conn.printFile(printer_name, path, filename, {})

        d = deferLater(reactor, 0, lambda: jobId)
        d.addCallback(self._put_to_monitor)
        d.addErrback(log.err)

    def render_GET(self, request):
        log.msg("URI: %s" % self.uri)
        if (self.uri == "print"):
            """
               Тут происходит обработка печатных форм
            """
            log.msg("Print args: %s" % request.args)
            log.msg("Print Headers: %s" % request.getAllHeaders())

            guid = request.args.get('guid')[0]
            FILE_LOCATION = "/tmp/amq/%s" % guid

            action = request.getHeader('print_type')

            if (action == "print"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно ее отправить на печать   
                """
                printer = request.getHeader('printer')

                d = deferLater(reactor, 0, lambda: {"path": FILE_LOCATION, "filename": guid, 'printer': printer})
                d.addCallback(self._print_job)
                d.addErrback(log.err)

                return "Send to print"

            elif (action == "preview"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно уведомить получателя о этом   
                """
                conf = {}
                conf['clientId'] = "CurrentClient"

                content = '<a href=" http://192.168.1.27:8080/get_preview?guid=%s">Preview done!</a>' % guid

                self.Send_Notify(content)

                return "Send notify"

            elif (action == "email"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и 
                   нужно уведомить получателя об этом и отправить е-мейл
                """
                host = 'localhost'
                sender = request.getHeader("sender")
                recipients = request.getHeader("email_recipients").split(",")
                message = request.getHeader("message")
                subject = request.getHeader("subject")
                attach = FILE_LOCATION

                send_email(message, subject, sender, recipients, host, attach)

                return "Задание поставлено"
            return "Test"

        elif (self.uri == "check_status"):
            """
               Тут мы обрабатываем проверку статуса печати документа
            """
            d = deferLater(reactor, 0, lambda: request)
            d.addCallback(self._get_print_status)
            d.addErrback(log.err)
            return NOT_DONE_YET

        elif (self.uri == "get_jrxml"):
            """
               Тут мы отдаем данные для JasperReport из которых он сгенерирует печатную форму
            """
            log.msg("get JRXML args: %s" % request.args)
            log.msg("get JRXML Headers: %s" % request.getAllHeaders())
            guid = request.args.get('guid', [None])[0]
            log.msg("Request: %s" % request.args)
            log.msg("Print guids: %s" % print_guids)
            if (find(lambda GUID: GUID == guid, print_guids)):
                result = self._get_from_stomp({"type": "queue", "name": "jasper_print_data_%s" % guid})
                print_guids.remove(guid)
            else:
                result = """
			<xml>
				Не положили print_data
				<foo>
					К терапевту!
				<foo>
			</xml>
                        """
            request.setHeader("Content-Type", "text/xml")
            log.msg("Очередь вернула данные в JasperReport: %s" % result)
            return result

        elif (self.uri == "get_preview"):
            """
            Возращает пользователю печатную форму.
            Возвращаемый тип документа - application/pdf
            """
            log.msg("get preview args: %s" % request.args)
            log.msg("get preview Headers: %s" % request.getAllHeaders())

            guid = request.args.get('guid')[0]
            FILE_LOCATION = "/tmp/amq/%s" % guid
            f = open(FILE_LOCATION)
            read_data = f.read()
            request.setHeader('Content-Length',  str(os.path.getsize(FILE_LOCATION)))
            request.setHeader('Content-Type', "application/pdf")
            try:
                os.unlink(FILE_LOCATION)
            except:
                pass
            return read_data

        else:
            return "OK"
    
     
    def render_POST(self, request):
        if (self.uri == "print"):
            """
               Получаем от пользователя XML
               Валидируем XML
               Отправляем XML на обработку в очередь
            """
            xml = etree.fromstring(request.args.get('xml', [None])[0])

            """
               Здесь задаем заголовки необходимые для обработки печатной формы
            """

            conf = {}

            d = datetime.utcnow()
            unix_timestamp = calendar.timegm(d.utctimetuple())

            type_of = ['nakladnaya', 'sborochnaya', 'dostavca']
            
            for type in type_of:
                xpath =  xml.xpath('//%s' % type)
                if len(xpath):
                    conf["Document-Type"] = xpath[0].tag


            """
               Разбиваем сообщение на две части - управляющую и данные
               Упаправляющую часть ...
               Часть с данным откладываем в ActiveMQ пока JasperReport
               не придет за ней
            """

            control_data = xml.xpath('//control_data')

            for child in control_data[0]:
                if not (child.text is None):
                   if len(child.text):
                       conf[child.tag] = child.text

            print_data = xml.xpath('//print_data')
            log.msg("print_data: %s" % print_data)

            """
               Для проверки на стадии отдачи print_data запишем GUID документа в список
            """
            if (isinstance(print_data, types.NoneType) == False):
                log.msg("Print_guids before: %s" % print_guids)
                print_guids.append(xml.xpath("//XML_GET_PARAM_guid")[0].text)

                log.msg("Print_guids after: %s" % print_guids)

                stomp_print_data = {"content": etree.tostring(print_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_print_data_%(XML_GET_PARAM_guid)s" % conf}, "conf": conf }
                stomp_control_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_jasper_control"}, "conf": conf }
                stomp_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_control_data"}, "conf": conf }

                stomp_data = {}
                stomp_data = [stomp_print_data, stomp_control_control_data, stomp_control_data]
  
                for item in stomp_data:
                    Producer().run(item)
            else:
                return "Bad comparation!"
            return "Ok!"

        elif (self.uri == "test"):
            log.msg("Headers: %s" % request.getAllHeaders())
            log.msg("Body: %s" % request.content.read())
            return "QE{"
        else:
            return "OK"

class Dispatcher(Resource):

  def getChild(self, name, request):
      return Simple(name)

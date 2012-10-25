#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.web.server import NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet.task import deferLater, defer
from twisted.python import log
from twisted.web import static
from twisted.web.static import File
import twisted.web.error as error

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

from urlparse import *

stringify = etree.XPath("string()")

print_guids = list()

def find(f, seq):
  """Return first item in sequence where f(item) == True."""
  for item in seq:
    if f(item): 
      return item

def send_email(message_text, subject, sender, recipients, host, attach = None):
    """
    Send email to one or more addresses.
    """

    import mailer

    message = mailer.Message()
    message.From = sender
    message.To = recipients
    message.Subject = subject
    message.Body = message_text
    if not (attach is None):
        message.attach(attach)

    mailer = mailer.Mailer('localhost')

    d = deferLater(reactor, 0, mailer.send, message)
    d.addErrback(log.err)
    return d

    

def Send_Notify(func_name = "window.toastr.success", func_args = [], recipient = ["*"], group = ["*"], profile = "user", callbackArgs = None, errbackArgs = None):
        log.msg("Отправка уведомления пользователю")
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
        log.msg("Control Message: %s" % ControlMessage)
        Producer().run(ControlMessage)

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
        message["body"] = {'func_name': 'window.toastr.error', 'func_args': ["Ошибка генерации документа", "Ошибка"]}
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

    def _put_to_monitor(self, data = {}):
        """
           Отправляем задание на печать в очередь мониторинга. Сообщения из очереди прилетают с задержкой в 300 секунд
        """
        log.msg("Отправка задания печати на мониторинг")
        conf = {}
        conf['message_group'] = data['conf']['message_group']
        conf['message_recipient'] = data['conf']['message_recipient']
        jobId = data["jobId"]
        conf['AMQ_SCHEDULED_DELAY'] = 3000
        conf['CamelCharsetName'] = 'UTF-8'
        data = {"content": jobId, "destination": {"type": "queue", "name": "twisted_status"}, 'conf': conf }
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
        conf = request.getAllHeaders()
        Attributes = self.conn.getJobAttributes(int(jobId))
        # Определяем нужные статусы печати - которые мы не мониторим
        success = [7,9]
        errors = [6,8,4]
        recipient =  request.getHeader('message_recipient').split(",")
        group = request.getHeader('message_group').split(",")

        # Если задание успешно напечаталось...
        if (Attributes['job-state'] in success):
            func_name = "window.toastr.success"
            func_args = ["Документ успешно напечатан!", "Печать завершена"]
            d = deferLater(reactor, 0, Send_Notify, func_name, func_args, recipient, group)
            d.addErrback(log.err)

        elif (Attributes['job-state'] in errors):
            func_name = "window.toastr.error"
            func_args = ["Во время печати документа произошла ошибка: %s" % Attributes['job-state'], "Печать завершилась с ошибкой"]
            d = deferLater(reactor, 0, Send_Notify, func_name, func_args, recipient, group)
            d.addErrback(log.err)
        else:
            # Нет, задание еще висит в очереди на печать. Отправляем его в очередь мониторинга
            self._put_to_monitor({"jobId": jobId, "conf": conf})
            func_name = "window.toastr.info"
            func_args = ["Печать еще не завершена.", "Идет печать"]
            d = deferLater(reactor, 0, Send_Notify, func_name, func_args, recipient, group)
            d.addErrback(log.err)
        request.write("Checked")
        request.finish()
                
    def _print_job(self, conf = None):
        # get printer name from filename
        printer_name = conf['printer']
        filename = conf['filename']
        path = conf['path']

        jobId = self.conn.printFile(printer_name, path, filename, {})

        d = deferLater(reactor, 0, self._put_to_monitor, {"jobId": jobId, "conf": conf})
        d.addErrback(log.err)

    def render_GET(self, request):
        log.msg("URI: %s" % self.uri)
        if (self.uri == "print"):
            """
               Тут происходит обработка печатных форм
            """
            log.msg("Print args: %s" % request.args)
            log.msg("Print Headers: %s" % request.getAllHeaders())

            guid = request.getHeader('xml_get_param_guid')
            type = request.getHeader('output')
            FILE_NAME = "%(filename)s.%(type)s" % {'filename': guid, 'type': type }

            FILE_LOCATION = "/tmp/amq/%s" % FILE_NAME

            action = request.getHeader('print_type')

            if (action == "print"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно ее отправить на печать   
                """
                conf = request.getAllHeaders()
                conf['path'] = FILE_LOCATION
                conf['filename'] = guid
                
                statinfo = os.stat(FILE_LOCATION)
                if (statinfo.st_size > 1024L):
                    d = deferLater(reactor, 0, self._print_job, conf)
                    d.addErrback(log.err)
                else:
                    recipient =  conf['message_recipient'].split(",")
                    group = conf['message_group'].split(",")

                    # Если задание успешно напечаталось...
                    func_name = "window.toastr.error"
                    func_args = ["Ашипка генерации документа - неправильный шаблон или данные", "Печать отменена"]
                    d = deferLater(reactor, 0, Send_Notify, func_name, func_args, recipient, group)
                    d.addErrback(log.err)


                return "Send to print"

            elif (action == "preview"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно уведомить получателя о этом   
                """
                scheme, netloc, path, _, _ = urlsplit(request.getHeader('XML_URL'))
                new_path = "/get_preview"
                query_string = "guid=%s" % FILE_NAME
                new_url = urlunsplit((scheme, netloc, new_path, query_string, _))
                content = '<a target="_blank" href="%s">Посмотреть документ</a>&#8230;' % new_url
                func_name = "window.toastr.success"
                func_args = [content, "Предпросмотр подготовлен"]
                recipient =  request.getHeader('message_recipient').split(",")
                group = request.getHeader('message_group').split(",")
                d = deferLater(reactor, 0, Send_Notify, func_name, func_args, recipient, group)
                d.addErrback(log.err)
                return "Send notify"

            elif (action == "email"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и 
                   нужно уведомить получателя об этом и отправить е-мейл
                """
                host = 'localhost'
                sender = request.getHeader("sender")
                recipients = request.getHeader("email_recipients")
                message = request.getHeader("message")
                subject = request.getHeader("subject")
                attach = FILE_LOCATION

                recipient =  request.getHeader('message_recipient').split(",")
                group = request.getHeader('message_group').split(",")


                df = send_email(message, subject, sender, recipients, host, attach)
                df.addCallback(Send_Notify, callbackArgs=("window.toastr.success", ["E-mail упешно отправлен!", "E-mail отправлен"], recipient, group))
                df.addErrback(Send_Notify, errbackArgs=("window.toastr.error", ["При отправке e-mail возникли проблемы!", "E-mail не отправлен"], recipient, group))

                return "Задание поставлено"
            return "Test"

        elif (self.uri == "check_status"):
            """
               Тут мы обрабатываем проверку статуса печати документа
            """
            d = deferLater(reactor, 0, self._get_print_status, request)
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

            guid = request.args.get("guid", [None])[0]

            FILE_LOCATION = "/tmp/amq/%s" % guid
            request.setHeader('Content-Length',  str(os.path.getsize(FILE_LOCATION)))
            request.setHeader('Content-Disposition', 'inline')
            file = static.File(FILE_LOCATION)
            return file.render(request)

        elif (self.uri == "send_email"):
            return "E-mail NOT sended. Just demo"
        else:
            return "OK"
    
     
    def render_POST(self, request):
        if (self.uri == "print"):
            """
               Получаем от пользователя XML
               Валидируем XML
               Отправляем XML на обработку в очередь
            """
            xml_args = request.args.get('xml', [None])[0]
            if xml_args is None:
                page = error.NoResource(message="Нет данных!")
                return page.render(request)
            else:
                xml = etree.fromstring(request.args.get('xml', [None])[0])

            """
               Здесь задаем заголовки необходимые для обработки печатной формы
            """

            conf = {}

            ## Установим заголовок для Camel
            conf["CamelCharsetName"] = "UTF-8"

            d = datetime.utcnow()
            unix_timestamp = calendar.timegm(d.utctimetuple())

            type_of = ['nakladnaya', 'sborochnaya', 'dostavca']
            
            for type in type_of:
                xpath =  xml.xpath('//%s' % type)
                if len(xpath):
                    conf["Document-Type"] = xpath[0].tag

#            if not ("message_recipient" in conf):
#                return "Кто будет получать сообщение о задании???"

#            if not ("message_group" in conf):
#                return "Какая группа будет получать сообщение о задании???"

#            if not ("reportUnit" in conf):
#                return "Укажите шаблон для генерации!!!"


            """
               Разбиваем сообщение на две части - управляющую и данные
               Управляющую часть ...
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

#            if ( conf["print_type"] == "print" ):
#                if not ("printer" in conf):
#                   return "Укажите принтер!"
#            elif ( conf["print_type"] == "preview" ):
#                pass
#            elif ( conf["print_type"] == "email" ):
#                if not ("sender" in conf ):
#                    return "Укажите отправителя сообщения"
#                if not (" email_recipients" in conf ):
#                    return "Укажите получателей сообщения"
#                if not ( "message" in conf ):
#                    return "Задайте сообщения к e-mail на аглицкой мове"
#                if not ( "subject" in conf ):
#                    return "Укажите тему письма"

            """
               Для проверки на стадии отдачи print_data запишем GUID документа в список
            """
            if (isinstance(print_data, types.NoneType) == False):
                log.msg("Print_guids before: %s" % print_guids)
                print_guids.append(xml.xpath("//XML_GET_PARAM_guid")[0].text)

                log.msg("Print_guids after: %s" % print_guids)
                conf['JMSExpiration'] = 5000
                stomp_print_data = {"content": etree.tostring(print_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_print_data_%(XML_GET_PARAM_guid)s" % conf}, "conf": conf }
                del conf['JMSExpiration']
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

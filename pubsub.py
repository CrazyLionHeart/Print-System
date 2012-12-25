#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.internet import reactor, defer
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

import os
import time
from datetime import datetime
import calendar

from lxml import etree

import json

import types

import requests

import sys
sys.path.append("/usr/local/bin")

from urlparse import *

from AMQ import *

amq = AMQ()

profile = "user"
tag = "print_system"

stringify = etree.XPath("string()")

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

class Simple(Resource):
    isLeaf = True

    def __init__(self, uri):
        Resource.__init__(self)
        self.uri = uri
        
        self.conn = cups.Connection()

    def _put_to_monitor(self, data = {}):
        """
           Отправляем задание на печать в очередь мониторинга. Сообщения из очереди прилетают с задержкой в 300 секунд
        """
        log.msg("Отправка задания печати на мониторинг")
        conf = {}
        conf['message_recipient'] = data['conf']['message_recipient']
        jobId = data["jobId"]
        conf['AMQ_SCHEDULED_DELAY'] = 3000
        conf['CamelCharsetName'] = 'UTF-8'
        data = {"content": jobId, "destination": {"type": "queue", "name": "twisted_status"}, 'conf': conf }
        d = deferLater(reactor, 0, amq.producer, data)
        d.addErrback(log.err)

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

        # Если задание успешно напечаталось...
        if (Attributes['job-state'] in success):
            func_name = "window.toastr.success"
            func_args = ["Документ успешно напечатан!", "Печать завершена"]
            d = deferLater(reactor, 0, amq.Send_Notify, func_name, func_args, recipient, profile, tag)
            d.addErrback(log.err)

        elif (Attributes['job-state'] in errors):
            func_name = "window.toastr.error"
            func_args = ["Во время печати документа произошла ошибка: %s" % Attributes['job-state'], "Печать завершилась с ошибкой"]
            d = deferLater(reactor, 0, amq.Send_Notify, func_name, func_args, recipient, profile, tag)
            d.addErrback(log.err)
        else:
            # Нет, задание еще висит в очереди на печать. Отправляем его в очередь мониторинга
            self._put_to_monitor({"jobId": jobId, "conf": conf})
            func_name = "window.toastr.info"
            func_args = ["Печать еще не завершена.", "Идет печать"]
            d = deferLater(reactor, 0, amq.Send_Notify, func_name, func_args, recipient, profile, tag)
            d.addErrback(log.err)
        request.write("Checked")
        request.finish()

    def parse_POST(self, request):
         """
               Получаем от пользователя XML
               Валидируем XML
               Отправляем XML на обработку в очередь
         """
         debug = list()

         input_xml = request.args.get('xml', [None])[0]

         if input_xml is None:
             input_xml = request.content.read()
             log.msg("Input xml: %s" % input_xml)
             debug.append("Input xml: %s" % input_xml)
         else:
             log.msg("Input xml: %s" % input_xml)
             debug.append("Input xml: %s" % input_xml)

         try:
             xml = etree.fromstring(input_xml)
         except (etree.XMLSyntaxError, ValueError), detail:
             log.msg( "Что за чушь вы мне подсунули? %s" % detail )
             request.write( "Что за чушь вы мне подсунули? %s" % detail )
             debug.append( "Что за чушь вы мне подсунули? %s" % detail )
         else:
             """
             Здесь задаем заголовки необходимые для обработки печатной формы
             """

             conf = {}

             ## Установим заголовок для Camel
             conf["CamelCharsetName"] = "UTF-8"
    
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
             log.msg("print_data: %s" % print_data )
             debug.append( "print_data: %s" % print_data )
             debug.append( "control_data: %s" % control_data )
             debug.append( "AMQ headers: %s" % conf )
    
             if (isinstance(print_data, types.NoneType) == False):
    
                 conf['JMSExpiration'] = 5000
                 stomp_print_data = {"content": etree.tostring(print_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_print_data_%(XML_GET_PARAM_guid)s" % conf}, "conf": conf }
                 del conf['JMSExpiration']
                 stomp_control_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_jasper_control"}, "conf": conf }
                 stomp_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_control_data"}, "conf": conf }
    
                 for item in [stomp_print_data, stomp_control_control_data, stomp_control_data]:
                     d = deferLater(reactor, 0, amq.producer, item)
                     d.addErrback(log.err)
#                     amq.producer(item)
             else:
                  log.msg( "Нет блока данных print_data" )
                  debug.append( "Нет блока данных print_data" )
                  request.write("Нет блока данных print_data!")
         if ('debug' in conf):
             for element in debug:
                 amq.Debug(conf['debug'], element)
         return

                
    def _print_job(self, conf = None):
        # get printer name from filename
        printer_name = conf['printer']
        filename = conf['filename']
        path = conf['path']

        jobId = self.conn.printFile(printer_name, path, filename, {})

        d = deferLater(reactor, 0, self._put_to_monitor, {"jobId": jobId, "conf": conf})
        d.addErrback(log.err)

    def render_GET(self, request):
        if (self.uri == "print"):
            """
               Тут происходит обработка печатных форм
            """
            debug = False

            headers = request.getAllHeaders()
            args = request.args

            log.msg("Print args: %s" % args)
            log.msg("Print Headers: %s" % headers)

            if "debug" in headers:
                debug = True  

            if debug == True:
                amq.Debug(headers['debug'], "Return headers from Camel: %s" % headers)
                amq.Debug(headers['debug'], "Return args from Camel: %s" % args)

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

                    # Если задание успешно напечаталось...
                    func_name = "window.toastr.error"
                    func_args = ["Ашипка генерации документа - неправильный шаблон или данные", "Печать отменена"]
                    d = deferLater(reactor, 0, amq.Send_Notify, func_name, func_args, recipient, profile, tag)
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

                d = deferLater(reactor, 0, amq.Send_Notify, func_name, func_args, recipient, profile, tag)
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

                df = send_email(message, subject, sender, recipients, host, attach)
                df.addCallback(amq.Send_Notify, callbackArgs=("window.toastr.success", ["E-mail упешно отправлен!", "E-mail отправлен"], recipient, profile, tag))
                df.addErrback(amq.Send_Notify, errbackArgs=("window.toastr.error", ["При отправке e-mail возникли проблемы!", "E-mail не отправлен"], recipient, profile, tag))

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
            request.setHeader("Content-Type", "text/xml")
            log.msg("get JRXML args: %s" % request.args)
            log.msg("get JRXML Headers: %s" % request.getAllHeaders())
            guid = request.args.get('guid', [None])[0]
            log.msg("Request: %s" % request.args)
            # Удаляем гланды через жопу - проверяем существует ли очередь с данными
            url = "http://localhost:8161/admin/xml/queues.jsp"

            # Получаем текущий статус очередей в ActiveMQ
            res = requests.get(url)
            queues_status = xml = etree.fromstring(res.content)
            xpath = queues_status.xpath("//queue[@name='jasper_print_data_%s']/stats" % guid)
            if not (xpath is None):
                for child in xpath:
                    if (child.attrib['size'] != 0 ):
                         print_data = amq.consumer("/queue/jasper_print_data_%s" % guid)
                         log.msg("Print_data: %s" % print_data)
                         return print_data

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
        elif (self.uri == "printers"):
             printer = request.args.get('printer', [None])[0]
             request.setHeader("Content-Type", "application/json")
             if printer is None:
                 return "%s" % json.dumps(self.conn.getPrinters(), sort_keys=True, indent=4)
             else:
                 return "%s" % json.dumps(self.conn.getPrinterAttributes(printer), sort_keys=True, indent=4)
        else:
            return "OK"
    
     
    def render_POST(self, request):
        log.msg(request)
        log.msg(request.getAllHeaders())
        if (self.uri == "print"):
            d = deferLater(reactor, 0, self.parse_POST, request)
            d.addErrback(log.err)
            return "Данные получил"

        elif (self.uri == "test"):
            log.msg("Headers: %s" % request.getAllHeaders())
            log.msg("Body: %s" % request.content.read())
            return "QE{"
        else:
            return "OK"

class Dispatcher(Resource):

  def getChild(self, name, request):
      return Simple(name)

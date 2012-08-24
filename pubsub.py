#!/bin/bash
# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.web.server import NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet.task import deferLater
from twisted.application import service, internet
from twisted.web import server
from twisted.application.service import Application
from twisted.application.internet import TCPServer
from twisted.web.server import Site
from twisted.python import log
from twisted.web.resource import ErrorPage
from twisted.python import usage

import cups

import urllib

from stompy.simple import Client

import os

from lxml import etree

stringify = etree.XPath("string()")

def find(f, seq):
  """Return first item in sequence where f(item) == True."""
  for item in seq:
    if f(item): 
      return item


class Simple(Resource):
    isLeaf = True

    def __init__(self, uri):
        Resource.__init__(self)
        self.uri = uri
        self.conn = cups.Connection()

    def _put_to_monitor(self, jobId):
        """
           Отправляем задание на печать в очередь мониторинга. Сообщения из очереди прилетают с задержкой в 300 секунд
        """
        log.info("Отправка задания печати на мониторинг")
        data = {"content": jobId, "destination": {"type": "queue", "name": "twisted_status"}, 'conf': {'AMQ_SCHEDULED_DELAY':300000, 'CamelCharsetName': 'UTF-8'} }
        self._put_to_stomp(data)

    def _put_to_stomp(self, data = {"content": None, "destination": {"type": None, "name": None}, "conf": {} }):
        """
           Отправляем сообщение в очередь используя протокол Stomp
        """
        log.info("Отправляем сообщение в очередь")
        stomp = Client()
        stomp.connect(username="admin", password="activemq")
        stomp.put(data['content'], destination = "/%(type)s/%(name)s" % data['destination'], conf =  data['conf'])
        stomp.disconnect()

    def _get_from_stomp(self, data = {"type": "queue", "name": "queue_name"}):
        """
           Получаем сообщение из очереди. Используем блокирующий вывод,
           так как непонятно сколько раз щемится в очередь до получения сообщения
        """
        log.info("Получаем сообщение из очереди")
        stomp = Client()
        stomp.connect(username="admin", password="activemq")
        destination = "/%(type)s/%(name)s" % data
        stomp.subscribe(destination)
        message = stomp.get()
        stomp.unsubscribe(destination)
        stomp.disconnect()
        return message.body


    def _get_preview_from_stomp(self, num_nakl, date_nakl):
        destinatination = {"type": "queue", "name": "jasper_preview_%(num_nakl)s_%(date_nakl)s" % {"num_nakl":num_nakl,"date_nakl":date_nakl}}
        self._get_from_stomp(destination)

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
                
    def _print_job(self, conf = None):
        # get printer name from filename
        printer_name = conf['printer']
        filename = urllib.url2pathname(conf['filename'])
        path = conf['path']

        jobId = self.conn.printFile(printer_name, path, filename, {})

        d = deferLater(reactor, 0, lambda: jobId)
        d.addCallback(self._put_to_monitor)
        d.addErrback(log.err)

    def _get_jrxml(self, request):
        """
           Возвращает JasperReport XML для генерации печатной
           формы.
           Возвращаемый тип документа - text/xml
        """

        log.msg("Request: %s" % request.getAllHeaders())
        log.msg("Args: %s" % request.args)
        conf = {}
        conf["XML_GET_PARAM_num_nakl"] = request.args.get('num_nakl', [None])[0]
        conf["XML_GET_PARAM_date_nakl"] = request.args.get('date_nakl', [None])[0]
        log.msg("JRXML conf: %s" % conf)

        read_data = self._get_from_stomp(data = {"type": "queue", "name": "jasper_print_data_%(XML_GET_PARAM_num_nakl)s_%(XML_GET_PARAM_date_nakl)s" % conf })
        log.msg("Read data from stomp: %s" % read_data)
        request.setHeader('Content-Type', "text/xml")
        request.write(read_data)
        request.finish()

    def _get_preview(self, request):
        """
           Возращает пользователю печатную форму.
           Возвращаемый тип документа - application/pdf
        """
        num_nakl = unicode(request.args.get('num_nakl', [None])[0], 'utf-8')
        date_nakl = unicode(request.args.get('date_nakl', [None])[0], 'utf-8')
        FILE_LOCATION = "/tmp/amq_preview/%(num_nakl)s_%(date_nakl)s" % {"num_nakl":num_nakl,"date_nakl":date_nakl}
        f = open(FILE_LOCATION)
	read_data = f.read()
        request.setHeader('Content-Length',  str(os.path.getsize(FILE_LOCATION)))
        request.setHeader('Content-Type', "application/pdf")
        request.write(read_data)
	os.ulink(FILE_LOCATION)
        request.finish()

    def render_GET(self, request):
        if (self.uri == "print"):
            """
               Тут происходит обработка печатных форм
            """
            log.msg("Print args: %s" % request.args)

            filename =  unicode(request.args.get('filename', [None])[0], 'utf-8')
            path = unicode(request.args.get('path', [None])[0], 'utf-8')
            action = request.getHeader('print_type')

            if (action == "print"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно ее отправить на печать   
                """
                d = deferLater(reactor, 0, lambda: {"path": path, "filename": filename, 'printer': printer})
                d.addCallback(self._print_job)
                d.addErrback(log.err)
                return "Send to print"
            elif (action == "preview"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и
                   нужно уведомить получателя о этом   
                """
                pass
            elif (action == "email"):
                """
                   Тут приходит уведомление от Camel о том что печатная форма  готова и 
                   нужно уведомить получателя об этом и отправить е-мейл
                """ 
                pass
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
            d = deferLater(reactor, 0, lambda: request)
            d.addCallback(self._get_jrxml)
            d.addErrback(log.err)
            return NOT_DONE_YET
        elif (self.uri == "get_preview"):
            """
               Тут мы отдаем пользователю сгенерированную печатную форму для просмотра
            """
            d = deferLater(reactor, 0, lambda: request)
            d.addCallback(self._get_preview)
            d.addErrback(log.err)
            return NOT_DONE_YET
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
            headers = ['XML_GET_PARAM_num_nakl', 'XML_GET_PARAM_date_nakl', 'print_type', 'backup_printer', 'reportUnit', 'XML_URL', 'printer']

            conf = {}

            for header in headers:
                xpath =  xml.xpath('//%s/text()' % header)
                if len(xpath):
                    conf[header] = xpath[0]

#            conf['XML_URL'] = conf['XML_URL'] + '?' + 'XML_GET_PARAM_num_nakl=' + conf['XML_GET_PARAM_num_nakl'] + '&' + 'XML_GET_PARAM_date_nakl=' + conf['XML_GET_PARAM_date_nakl']

            """
               Разбиваем сообщение на две части - управляющую и данные
               Упаправляющую часть ...
               Часть с данным откладываем в ActiveMQ пока JasperReport
               не придет за ней
            """

            control_data = xml.xpath('//control_data')
            print_data = xml.xpath('//print_data')

            stomp_print_data = {"content": etree.tostring(print_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_print_data_%(XML_GET_PARAM_num_nakl)s_%(XML_GET_PARAM_date_nakl)s" % conf}, "conf": conf }
            stomp_control_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_jasper_control"}, "conf": conf }
            stomp_control_data = {"content": etree.tostring(control_data[0], encoding='utf-8', pretty_print=True), "destination": {"type": "queue", "name": "jasper_control_data"}, "conf": conf }
            
            d1 = deferLater(reactor, 0, lambda: stomp_print_data)
            d1.addCallback(self._put_to_stomp)
            d1.addErrback(log.err)

            d2 = deferLater(reactor, 0, lambda: stomp_control_control_data)
            d2.addCallback(self._put_to_stomp)
            d2.addErrback(log.err)
            
            d2 = deferLater(reactor, 0, lambda: stomp_control_data)
            d2.addCallback(self._put_to_stomp)
            d2.addErrback(log.err)

            return "XML parsed"            
        elif (self.uri == "test"):
            log.msg("Headers: %s" % request.getAllHeaders())
            log.msg("Body: %s" % request.content.read())
            return "QE{"
        else:
            return "OK"


class Dispatcher(Resource):
  def getChild(self, name, request):
      return Simple(name)

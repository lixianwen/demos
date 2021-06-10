#!/usr/bin/env python

import socket
import selectors

sel = selectors.DefaultSelector()

def read(sock, mask):
    data = sock.recv(1024)     # Should be ready
    if data:
        print('Received data:', repr(data), 'to', sock)
        sel.unregister(sock)
        sock.close()


def initiat_connect(num: int):
    """:param num: number of connections"""
    for i in range(0, num):
        s = socket.socket()
        s.setblocking(False)
        s.connect_ex(('127.0.0.1', 80))
        sel.register(s, selectors.EVENT_READ, read)
        s.send(bytes('Message from client-%s' % i, 'utf-8'))


try:
    initiat_connect(2)

    while True:
        fd_list = sel.select()  # blocking

        for key, events in fd_list: # Contain connected socket 
            callback = key.data   # `key` is a selectors.SelectorKey instance
            callback(key.fileobj, events)

        if not sel.get_map():
            break
finally:
    sel.close()

#!/usr/bin/env python

import socket


HOST = '127.0.0.1'

PORT = 80

with socket.socket() as s:
    s.connect((HOST, PORT))
    s.sendall(b'hello python')
    data = s.recv(1024)

    print('Received', repr(data))

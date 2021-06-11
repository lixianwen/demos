import selectors
import socket

sel = selectors.DefaultSelector()

def accept(sock, mask):
    print('accept callback')
    conn, addr = sock.accept()  # Should be ready
    print('Accpeted connection from', addr)
    conn.setblocking(False)
    sel.register(conn, selectors.EVENT_READ, read)


def read(conn, mask):
    """Note: we didn't consider how long the message it is here"""
    print('read callback')
    data = conn.recv(1024)     # Should be ready
    if data:
        print('Echoing', repr(data), 'to', conn)
        sent = conn.send(data)
        print('Have sent', sent)
    else:
        print('closing', conn)
        sel.unregister(conn)
        conn.close()


s = socket.socket()
s.bind(('localhost', 80))
# listen() has a backlog parameter.
# It specifies the number of unaccepted connections that the system will allow before refusing new connections.
# Starting in Python 3.5, it's optional. If not specified, a default backlog value is chosen.

# If your server receives a lot of connection requests simultaneously,
# increasing the backlog value may help by setting the maximum length of the queue for pending connections.
# The maximum value is system dependent. For example, on Linux, see /proc/sys/net/core/somaxconn.

# Reference: https://realpython.com/python-sockets/
s.listen()
# To configure the socket in non-blocking mode, which means socket methods call return immediately.
# If we don't, the entire server is stalled until it's methods returned.
s.setblocking(False)

sel.register(s, selectors.EVENT_READ, accept)

try:
    while True:
        fd_list = sel.select()  # blocking
        for key, events in fd_list: # Contain listening socket and/or connected socket 
            callback = key.data   # `key` is a selectors.SelectorKey instance
            callback(key.fileobj, events)
finally:
    s.close()
    sel.unregister(s)
    sel.close()

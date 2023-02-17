import socket


def detect_listening_port(host: str, port: int, socket_timeout: int = 5, max_backoff: int = 3) -> bool:
    result = False
    initial_backoff = max_backoff

    while max_backoff >= 0:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(int(socket_timeout))
                s.connect((host, int(port)))
                s.shutdown(2)
                result = True
            break
        except OSError as e:
            max_backoff -= 1
            retry = initial_backoff - max_backoff
            if retry <= initial_backoff:
                print(f'Retry: {retry}')
                print(f'OS error occurred, {e!r}')

    return result


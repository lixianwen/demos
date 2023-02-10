import time
import threading

from .ssh_client import SSHClientV2


def detect_sftp_obj(client: SSHClientV2) -> None:
    start = time.perf_counter()
    print('Start: ', time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    thread_name = threading.current_thread().name
    sftp = client.sftp
    print(f"Thread: {thread_name}, id(sftp)={id(sftp)}")
    time.sleep(5)
    print('End: ', time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    print(f'Cost: {time.perf_counter() - start}')


client = SSHClientV2(hostname='192.168.1.1', port=22, username='root', password='a')
t1 = threading.Thread(target=detect_sftp_obj, args=(client,))
t2 = threading.Thread(target=detect_sftp_obj, args=(client,))
try:
    t1.start()
    # Block the main thread for prevent call `client.close`
    t1.join()
    t2.start()
    # Block the main thread for prevent call `client.close`
    t2.join()
finally:
    client.close()

"""another way"""
# with SSHClientV2(hostname='192.168.1.1', port=22, username='root', password='a') as client:
#     # We can use a with statement to ensure threads are cleaned up promptly
#     with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
#         # Start the load operations and mark each future with its URL
#         future_to_url = {executor.submit(detect_sftp_obj, client): i for i in range(2)}
#         for future in concurrent.futures.as_completed(future_to_url):
#             future.result()


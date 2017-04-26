import os
import re
import sys
import queue
import datetime
import threading
import requests

o = re.compile(r'(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) .* .* \[(?P<time>.*)\] "(?P<method>\w+) (?P<url>[^\s]*) (?P<version>[\w|/\.\d]*)" (?P<status>\d{3}) (?P<length>\d+) "(?P<referer>[^\s]*)" "(?P<ua>.*)"')
event = threading.Event()


def read_log(q, path):
    offset = 0
    while not event.is_set():
        with open(path) as f:
            if offset > os.stat(path).st_size:
                offset = 0
            f.seek(offset)
            for line in f:
                q.put(line)
            offset = f.tell()
        event.wait(0.1)


def read_worker(q, path):
    t = threading.Thread(target=read_log, name='read-{}'.format(path), args=(q, path), daemon=True)
    t.start()


def parse(q):
    while not event.is_set():
        line = q.get()
        m = o.search(line.rstrip('\n'))
        if m:
            data = m.groupdict()
            yield data


def agg(q, interval=10):
    count = 0
    traffic = 0
    error = 0
    start = datetime.datetime.now()
    for item in parse(q):
        print(item)
        count += 1
        traffic += int(item['length'])
        if int(item['status']) >= 300:
            error += 1
        current = datetime.datetime.now()
        if (current - start).total_seconds() >= interval:
            error_rate = error / count
            send(count, traffic, error_rate)
            start = current
            count = 0
            traffic = 0
            error = 0


def send(count, traffic, error_rate):
    line = 'access_log count={},traffic={},error_rate={}'.format(count, traffic, error_rate)
    res = requests.post('http://127.0.0.1:8086/write', data=line, params={'db': 'magedu'})
    if res.status_code >= 300:
        print(res.content)


def manager(*paths):
    q = queue.Queue()
    for path in paths:
        read_worker(q, path)
    agg(q, 10)

if __name__ == '__main__':
    manager(*sys.argv[1:])

import os
import re
import sys
import datetime
import threading
import requests
import multiprocessing

o = re.compile(r'(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) .* .* \[(?P<time>.*)\] "(?P<method>\w+) (?P<url>[^\s]*) (?P<version>[\w|/\.\d]*)" (?P<status>\d{3}) (?P<length>\d+) "(?P<referer>[^\s]*)" "(?P<ua>.*)"')
event = multiprocessing.Event()


def read_log(path, q):
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


def read_worker(path, q):
    t = threading.Thread(target=read_log, name='reader-{}'.format(path), args=(path, q))
    t.daemon = True
    t.start()


def parse(in_queue, out_queue):
    while not event.is_set():
        line = in_queue.get()
        m = o.search(line.rstrip('\n'))
        if m:
            data = m.groupdict()
            out_queue.put(data)


def agg(in_queue, out_queue, interval=10):
    count = 0
    traffic = 0
    error = 0
    start = datetime.datetime.now()
    while not event.is_set():
        item = in_queue.get()
        count += 1
        traffic += int(item['length'])
        if int(item['status']) >= 300:
            error += 1
        current = datetime.datetime.now()
        if (current - start).total_seconds() >= interval:
            out_queue.put((count, traffic, error))
            start = current
            count = 0
            traffic = 0
            error = 0


def agg_manager(q, interval=10, proc_num=4):
    queues = []
    for i in range(proc_num):
        out_queue = multiprocessing.Queue()
        queues.append(out_queue)
        p = multiprocessing.Process(target=agg, name='agg-{}'.format(i), args=(q, out_queue, interval))
        p.daemon = True
        p.start()
    while not event.is_set():
        total_count = 0
        total_traffic = 0
        total_error = 0
        for x in queues:
            count, traffic, error = x.get()
            total_count += count
            total_traffic += traffic
            total_error += error
        send(total_count, total_traffic, total_error/total_count)
        print((total_count, total_traffic, total_error/total_count))
    for x in queues:
        x.close()


def send(count, traffic, error_rate):
    line = 'nginx_access_log count={},traffic={},error_rate={}'.format(count, traffic, error_rate)
    res = requests.post('http://192.168.31.78:8086/write', data=line, params={'db': 'db_wsescape'})
    if res.status_code >= 300:
        print(res.content)


def manager(*paths):
    read_queue = multiprocessing.Queue()
    parse_queue = multiprocessing.Queue()
    for path in paths:
        read_worker(path, read_queue)
    for i in range(4):
        p = multiprocessing.Process(target=parse, name='parse-{}'.format(i), args=(read_queue, parse_queue))
        p.daemon = True
        p.start()
    agg_manager(parse_queue)

if __name__ == '__main__':
    try:
        manager(*sys.argv[1:])
    except KeyboardInterrupt:
        event.set()

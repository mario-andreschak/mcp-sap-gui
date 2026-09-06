import time


def hang(pipe, config):
    pipe.recv()
    time.sleep(20)


def echo(pipe, config):
    try:
        while True:
            item = pipe.recv()
            if item is None:
                break
            pipe.send({"result": {"method": item["method"]}})
    finally:
        pipe.close()

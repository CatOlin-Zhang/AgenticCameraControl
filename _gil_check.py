"""实测 hashlib.scrypt 线程并行度（决定构建期并行派生方案）。"""
import hashlib
import threading
import time

N = 2 ** 15
ARGS = dict(r=8, p=1, dklen=64, maxmem=(1 << 31) - 1)


def one(salt):
    hashlib.scrypt(salt, salt=salt, n=N, **ARGS)


t0 = time.perf_counter()
one(b"saltaaaa")
one(b"saltbbbb")
seq = time.perf_counter() - t0

t0 = time.perf_counter()
threads = [threading.Thread(target=one, args=(b"saltaaaa",)),
           threading.Thread(target=one, args=(b"saltbbbb",))]
for t in threads:
    t.start()
for t in threads:
    t.join()
par = time.perf_counter() - t0

print("serial 2x: %.3fs | parallel 2 threads: %.3fs | speedup: %.2fx"
      % (seq, par, seq / par))

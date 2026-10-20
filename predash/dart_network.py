"""Credential-free direct DNS/TCP/TLS/HTTP diagnostics for one fixed DART host.

Never accept an arbitrary URL, include API query parameters, or log exception text.
The direct probe is distinct from requests' possible proxy route and API authorization.
"""
import os
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
from predash.ttm import now

HOST='opendart.fss.or.kr'


def resolve():
    executor=ThreadPoolExecutor(max_workers=1)
    future=executor.submit(socket.getaddrinfo,HOST,443,type=socket.SOCK_STREAM)
    try:return future.result(timeout=2)
    finally:executor.shutdown(wait=False,cancel_futures=True)


def diagnose():
    result={'version':1,'host':HOST,'checked_at':now(),'route':'direct_tls_no_credentials',
        'proxy_configured':any(bool(os.getenv(k)) for k in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')),
        'stages':[],'scope':'인증키 없는 직접 연결 점검 · API 인증·프록시 경로 성공과 구분'}
    stage='DNS';started=time.monotonic();raw=None;secure=None
    def success(**extra):
        result['stages'].append({'stage':stage,'status':'success','elapsed_ms':round((time.monotonic()-started)*1000),**extra})
    try:
        addresses=resolve()
        usable=[a for a in addresses if a[0] in (socket.AF_INET,socket.AF_INET6)]
        if not usable:raise OSError('no addresses')
        success(ipv4_available=any(a[0]==socket.AF_INET for a in usable),ipv6_available=any(a[0]==socket.AF_INET6 for a in usable))
        stage='TCP';started=time.monotonic()
        selected=next((a for a in usable if a[0]==socket.AF_INET),usable[0])
        raw=socket.socket(selected[0],socket.SOCK_STREAM);raw.settimeout(3)
        raw.connect(selected[4]);success()
        stage='TLS';started=time.monotonic()
        raw.settimeout(4);secure=ssl.create_default_context().wrap_socket(raw,server_hostname=HOST)
        success()
        stage='HTTP';started=time.monotonic();secure.settimeout(4)
        secure.sendall(b'HEAD / HTTP/1.1\r\nHost: opendart.fss.or.kr\r\nConnection: close\r\n\r\n')
        header=b''
        while b'\r\n' not in header and len(header)<4096:
            remaining=4-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('HTTP deadline')
            secure.settimeout(remaining)
            chunk=secure.recv(min(1024,4096-len(header)))
            if not chunk:break
            header+=chunk
        line=header.split(b'\r\n',1)[0].split()
        if len(line)<2 or not line[0].startswith(b'HTTP/') or not line[1].isdigit():raise ValueError('invalid HTTP')
        status=int(line[1])
        if not 100<=status<=599:raise ValueError('invalid status')
        success(http_status=status)
        result['conclusion']='공개 호스트 HTTP 응답 도달 · API 경로·인증 및 프록시는 별도 확인 필요'
    except (OSError,ssl.SSLError,FutureTimeout,ValueError):
        result['stages'].append({'stage':stage,'status':'failed','elapsed_ms':round((time.monotonic()-started)*1000)})
        result['conclusion']={'DNS':'앱 서버의 DART 호스트 이름 조회 실패·시간 초과',
            'TCP':'이름 조회 후 DART TCP 443 연결 실패·시간 초과',
            'TLS':'TCP 연결 후 DART TLS 인증·연결 실패',
            'HTTP':'TLS 연결 후 DART HTTP 응답 확인 실패'}[stage]
    finally:
        try:
            if secure is not None:secure.close()
            elif raw is not None:raw.close()
        except OSError:pass
    return result

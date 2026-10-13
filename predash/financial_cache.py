"""Bounded, process-local cache of public financial evidence; never stores clients."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic


class FinancialCache:
    def __init__(self, ttl=86400, partial_ttl=300, max_entries=64, clock=monotonic):
        self.ttl = ttl
        self.partial_ttl = partial_ttl
        self.max_entries = max_entries
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = RLock()

    def get(self, code, loader, force=False):
        # Serialize fills so concurrent Streamlit sessions do not duplicate requests.
        # loader (and its credentials) is used only during this call, never retained.
        with self.lock:
            entry = self.entries.get(code)
            if not force and entry and self.clock() - entry['loaded'] < entry['ttl']:
                self.entries.move_to_end(code)
                return deepcopy(entry['data']), '저장 자료 재사용'
            # Exceptions leave the old snapshot intact without extending its lifetime.
            data = loader()
            if data.get('code') != code or not data.get('rows'):
                raise ValueError('재무 응답 종목 또는 자료 확인 필요')
            ttl = self.partial_ttl if data.get('data_gaps') else self.ttl
            self.entries[code] = {'data': deepcopy(data), 'loaded': self.clock(), 'ttl': ttl}
            self.entries.move_to_end(code)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)
            return deepcopy(data), 'DART 새로 조회'

    def remaining(self, code, fetched_at):
        with self.lock:
            entry = self.entries.get(code)
            if not entry or entry['data'].get('fetched_at') != fetched_at:
                return 0
            return max(0, entry['ttl'] - (self.clock() - entry['loaded']))

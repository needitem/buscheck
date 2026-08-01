# -*- coding: utf-8 -*-
"""코레일 모바일 API가 요구하는 x-dynapath-m-token 을 만든다.

코레일 앱 API(smart.letskorail.com)는 앱이 아닌 클라이언트를 "MACRO ERROR" 로
막는다. 이 토큰 헤더를 붙이면 정상 조회로 통과한다.

토큰 생성 로직은 MIT 라이선스인 @nomadamas/k-skill 의
skills/ktx-booking/scripts/ktx_booking.py (DynaPathMasterEngine) 에서 가져왔다.
표준 라이브러리만 쓰므로 buscheck 의 "추가 설치 불필요" 원칙을 유지한다.
"""

import time


class DynaPathEngine:
    APP_ID = "com.korail.talk"
    AS_VALUE = "%5B38ff229cb34c7dda8e28220a2d750cce%5D"
    DEVICE_MODEL = "SM-S928N"
    OS_TYPE = "Android"
    SDK_VERSION = "v1"

    def __init__(self):
        self.table = "3FE9jgRD4KdCyuawklqGJYmvfMn15P7US8XbxeLQtWT6OicBAopINs2Vh0HZrz"
        self.i8 = 161
        self.i9 = 30
        self.i10 = 2
        self.app_start_ts = str(int(time.time() * 1000))

    def string2xa1s(self, data):
        result = []
        idx = 0
        while idx < len(data):
            codepoint = ord(data[idx])
            idx += 1
            if codepoint < 128:
                result.append(codepoint)
            elif codepoint < 2048:
                result.append(128 | ((codepoint >> 7) & 15))
                result.append(codepoint & 127)
            elif codepoint >= 262144:
                result.append(160)
                result.append((codepoint >> 14) & 127)
                result.append((codepoint >> 7) & 127)
                result.append(codepoint & 127)
            elif (63488 & codepoint) != 55296:
                result.append(((codepoint >> 14) & 15) | 144)
                result.append((codepoint >> 7) & 127)
                result.append(codepoint & 127)
        return result

    def make_key(self, key):
        total = 0
        for char in key:
            codepoint = ord(char)
            bit = 32768
            for _ in range(16):
                if bit & codepoint:
                    break
                bit >>= 1
            total = (total * (bit << 1)) + codepoint
        return total

    def internal_char(self, base_table, remainder, current):
        seen = 0
        for char in base_table:
            if char in current:
                continue
            if seen == remainder:
                return char
            seen += 1
        return " "

    def make_encode_table(self, number, encode_size, base_table):
        chars = ""
        temp = number
        for index in range(encode_size):
            divisor = encode_size - index
            remainder = temp % divisor
            chars += self.internal_char(base_table, remainder, chars)
            temp //= divisor
        return chars

    def encode_normal_be(self, data, table):
        values = self.string2xa1s(data)
        output = []
        digits = [0] * (self.i10 + 1)
        idx = 0
        tail = len(values) % self.i10
        body_size = len(values) - tail
        while idx < body_size:
            value = 0
            for _ in range(self.i10):
                value = (value * self.i8) + values[idx]
                idx += 1
            for digit_index in range(self.i10 + 1):
                digits[digit_index] = value % self.i9
                value //= self.i9
            for digit_index in range(self.i10, -1, -1):
                output.append(table[digits[digit_index]])
        if tail > 0:
            value = 0
            for _ in range(tail):
                value = (value * self.i8) + values[idx]
                idx += 1
            for digit_index in range(tail + 1):
                digits[digit_index] = value % self.i9
                value //= self.i9
            while tail >= 0:
                output.append(table[digits[tail]])
                tail -= 1
        return "".join(output)

    def generate_token(self, device_id, timestamp_ms, nonce):
        plaintext = (
            f"ai={self.APP_ID}&di={device_id}&as={self.AS_VALUE}"
            f"&su=false&dbg=false&emu=false&hk=false"
            f"&it={self.app_start_ts}&ts={timestamp_ms}&rt=0&os=13"
            f"&dm={self.DEVICE_MODEL}&st={self.OS_TYPE}&sv={self.SDK_VERSION}"
        )
        dyn_key = f"v1+{nonce}+{timestamp_ms}"
        key_encoded = self.encode_normal_be(dyn_key, self.table)
        table = self.make_encode_table(self.make_key(dyn_key), self.i9, self.table)
        body_encoded = self.encode_normal_be(plaintext, table)
        return f"bEeEP{self.table[len(key_encoded)]}{key_encoded}{body_encoded}"

# Copyright 2021 Josh Steffen
#
# This file is part of Quatch.
#
# Quatch is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Quatch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Quatch; If not, see <https://www.gnu.org/licenses/>.

import binascii


def align(n, alignment):
    return n + (alignment - (n % alignment)) % alignment


def pad(data, alignment, padding=b"\0"):
    return data + padding * (align(len(data), alignment) - len(data))


def crc32(data):
    return binascii.crc32(data)


def forge_crc32(data, offset, crc):
    """Overwrite data[offset:offset + 4] to make data's CRC-32 checksum equal crc.

    For details see Reversing CRC - Theory and Practice.
    https://sar.informatik.hu-berlin.de/research/publications/SAR-PR-2006-05/SAR-PR-2006-05_.pdf
    """

    def pack(x):
        return x.to_bytes(4, "little")

    data[offset : offset + 4] = pack(crc32(data[:offset]) ^ 0xFFFFFFFF)
    data[offset : offset + 4] = pack(_crc32_reverse(data[offset:], crc))


def _crc32_reverse(data, crc):
    """Return the state the crc register would need to be in just before processing
    data in order to produce the desired checksum.
    """
    reg = crc ^ 0xFFFFFFFF
    for byte in reversed(data):
        reg = (reg << 8) ^ _crc32_reverse_table[reg >> 24] ^ byte
        reg &= 0xFFFFFFFF
    return reg


def _gen_crc32_reverse_table():
    table = []
    for i in range(256):
        reg = i << 24
        for _ in range(8):
            if reg & (1 << 31):
                reg = ((reg ^ 0xEDB88320) << 1) | 1
            else:
                reg <<= 1
        table.append(reg)
    return table


_crc32_reverse_table = _gen_crc32_reverse_table()

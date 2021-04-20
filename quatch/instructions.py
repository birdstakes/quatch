# Copyright 2021 Josh Steffen
#
# This file is part of Quatch.
#
# Quatch is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Quatch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Quatch; If not, see <https://www.gnu.org/licenses/>.

import enum
import io
import struct


class Opcode(enum.IntEnum):
    UNDEF = 0
    IGNORE = 1
    BREAK = 2
    ENTER = 3
    LEAVE = 4
    CALL = 5
    PUSH = 6
    POP = 7
    CONST = 8
    LOCAL = 9
    JUMP = 10
    EQ = 11
    NE = 12
    LTI = 13
    LEI = 14
    GTI = 15
    GEI = 16
    LTU = 17
    LEU = 18
    GTU = 19
    GEU = 20
    EQF = 21
    NEF = 22
    LTF = 23
    LEF = 24
    GTF = 25
    GEF = 26
    LOAD1 = 27
    LOAD2 = 28
    LOAD4 = 29
    STORE1 = 30
    STORE2 = 31
    STORE4 = 32
    ARG = 33
    BLOCK_COPY = 34
    SEX8 = 35
    SEX16 = 36
    NEGI = 37
    ADD = 38
    SUB = 39
    DIVI = 40
    DIVU = 41
    MODI = 42
    MODU = 43
    MULI = 44
    MULU = 45
    BAND = 46
    BOR = 47
    BXOR = 48
    BCOM = 49
    LSH = 50
    RSHI = 51
    RSHU = 52
    NEGF = 53
    ADDF = 54
    SUBF = 55
    DIVF = 56
    MULF = 57
    CVIF = 58
    CVFI = 59


operand_sizes = {
    Opcode.ENTER: 4,
    Opcode.LEAVE: 4,
    Opcode.CONST: 4,
    Opcode.LOCAL: 4,
    Opcode.BLOCK_COPY: 4,
    Opcode.ARG: 1,
}
operand_sizes.update({op: 4 for op in range(Opcode.EQ, Opcode.GEF + 1)})
operand_sizes.update({op: 0 for op in Opcode if op not in operand_sizes})


class Instruction:
    def __init__(self, opcode, operand=None):
        self.opcode = opcode
        self.operand = operand
        self.operand_size = operand_sizes[opcode]

        if self.operand_size != 0 and operand is None:
            raise TypeError(f'{opcode.name} requires an operand')

    def __repr__(self):
        if self.operand_size != 0:
            return f'{self.opcode.name} {self.operand:#x}'
        else:
            return f'{self.opcode.name}'

    def assemble(self):
        code = self.opcode.to_bytes(1, 'little')
        if self.operand is not None:
            code += self.operand.to_bytes(
                self.operand_size, 'little', signed=self.operand < 0
            )
        return code


def assemble(instructions):
    code = bytearray()
    for instruction in instructions:
        code += instruction.assemble()
    return code


def disassemble(code):
    code = io.BytesIO(code)
    instructions = []

    while True:
        byte = code.read(1)
        if byte == b'':
            break

        opcode = Opcode(int.from_bytes(byte, 'little'))

        if operand_sizes[opcode] != 0:
            operand = int.from_bytes(
                code.read(operand_sizes[opcode]), 'little'
            )
        else:
            operand = None

        instructions.append(Instruction(opcode, operand))

    return instructions

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

"""Qvm instructions and their assembly and disassembly."""

from __future__ import annotations

import enum
import io
import struct
from collections.abc import Iterable
from itertools import islice
from typing import Optional, Union


Operand = Union[int, float]


class Opcode(enum.IntEnum):
    """The operation performed by an instruction.

    See https://www.icculus.org/~phaethon/q3mc/q3vm_specs.html for details.
    """

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
operand_sizes.update({op: 4 for op in islice(Opcode, Opcode.EQ, Opcode.GEF + 1)})
operand_sizes.update({op: 0 for op in Opcode if op not in operand_sizes})


class Instruction:
    """A qvm instruction.

    An Instruction consists of an Opcode and optionally an integer or floating point
    operand, depending on the opcode.

    The BLOCK_COPY, ENTER, LEAVE, LOCAL, and comparison (EQ through GEF) opcodes require
    a 32-bit signed or unsigned integer operand.

    The CONST opcode requires either a 32-bit integer or a 32-bit float.

    The ARG opcode requires an 8-bit integer.

    All other opcodes have no operand.

    Example usage:

        >>> from quatch.instruction import Instruction, Opcode
        >>> Instruction(Opcode.PUSH)
        Instruction(Opcode.PUSH)
        >>> Instruction(Opcode.CONST, 123)
        Instruction(Opcode.CONST, 0x7b)
    """

    def __init__(self, opcode: Opcode, operand: Optional[Operand] = None) -> None:
        """Initialize an Instruction from an opcode and operand."""
        self._opcode: Opcode = opcode
        self._operand: Optional[Operand] = None

        if operand is not None:
            self.operand = operand
        elif operand_sizes[opcode] != 0:
            raise TypeError(f"{opcode.name} requires an operand")

    def __repr__(self) -> str:
        if self._operand is None:
            return f"Instruction({self._opcode!s})"
        elif isinstance(self._operand, float):
            return f"Instruction({self._opcode!s}, {self._operand})"
        else:
            return f"Instruction({self._opcode!s}, {self._operand:#x})"

    def __str__(self) -> str:
        if self._operand is None:
            return f"{self._opcode.name}"
        elif isinstance(self._operand, float):
            return f"{self._opcode.name} {self._operand}"
        else:
            return f"{self._opcode.name} {self._operand:#x}"

    @property
    def opcode(self) -> Opcode:
        return self._opcode

    @property
    def operand(self) -> Operand:
        if self._operand is None:
            raise AttributeError(f"{self._opcode.name} does not have an operand")
        return self._operand

    @operand.setter
    def operand(self, value: Operand) -> None:
        size = operand_sizes[self._opcode]
        if size == 0:
            raise TypeError(f"{self._opcode.name} does not take an operand")

        if isinstance(value, float):
            if self._opcode != Opcode.CONST:
                raise ValueError("only CONST can take a float operand")
            try:
                struct.pack("<f", value)
            except struct.error:
                raise ValueError("operand does not fit in a 32 bit float")
            self._operand = value
            return

        min_value = -(2 ** (size * 8 - 1))
        max_value = 2 ** (size * 8) - 1
        if not min_value <= value <= max_value:
            raise ValueError(f"operand out of range for {self._opcode.name}")

        self._operand = value

    def assemble(self) -> bytes:
        r"""Assemble a single Instruction into bytes.

        Example usage:

            >>> from quatch.instruction import Instruction, Opcode
            >>> Instruction(Opcode.PUSH).assemble()
            b'\x06'
            >>> Instruction(Opcode.CONST, 123).assemble()
            b'\x08{\x00\x00\x00'
        """
        code = self._opcode.to_bytes(1, "little")
        if isinstance(self._operand, float):
            code += struct.pack("<f", self._operand)
        elif self._operand is not None:
            code += self._operand.to_bytes(
                operand_sizes[self._opcode], "little", signed=self._operand < 0
            )
        return code


def assemble(instructions: Iterable[Instruction]) -> bytes:
    r"""Assemble Instructions into bytes.

    Example usage:

        >>> from quatch.instruction import Instruction as Ins, Opcode as Op
        >>> from quatch.instruction import assemble
        >>> assemble([Ins(Op.PUSH), Ins(Op.CONST, 123)])
        bytearray(b'\x06\x08{\x00\x00\x00')
    """
    code = bytearray()
    for instruction in instructions:
        code += instruction.assemble()
    return code


def disassemble(code: bytes) -> list[Instruction]:
    r"""Disassemble bytes into Instructions.

    Example usage:

        >>> from quatch.instruction import disassemble
        >>> disassemble(b'\x06\x08\x7b\x00\x00\x00')
        [Instruction(Opcode.PUSH), Instruction(Opcode.CONST, 0x7b)]
    """
    stream = io.BytesIO(code)
    instructions = []

    while True:
        byte = stream.read(1)
        if byte == b"":
            break

        opcode = Opcode(int.from_bytes(byte, "little"))

        if operand_sizes[opcode] != 0:
            operand = int.from_bytes(stream.read(operand_sizes[opcode]), "little")
            instructions.append(Instruction(opcode, operand))
        else:
            instructions.append(Instruction(opcode))

    return instructions

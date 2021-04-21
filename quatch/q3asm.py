# Copyright 1999-2005 Id Software, Inc.
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

from .instructions import Instruction as Ins, Opcode as Op
from .util import align, pad

opcode_map = {
    "BREAK": Op.BREAK,
    "CNSTF4": Op.CONST,
    "CNSTI4": Op.CONST,
    "CNSTP4": Op.CONST,
    "CNSTU4": Op.CONST,
    "CNSTI2": Op.CONST,
    "CNSTU2": Op.CONST,
    "CNSTI1": Op.CONST,
    "CNSTU1": Op.CONST,
    "ASGNB": Op.BLOCK_COPY,
    "ASGNF4": Op.STORE4,
    "ASGNI4": Op.STORE4,
    "ASGNP4": Op.STORE4,
    "ASGNU4": Op.STORE4,
    "ASGNI2": Op.STORE2,
    "ASGNU2": Op.STORE2,
    "ASGNI1": Op.STORE1,
    "ASGNU1": Op.STORE1,
    "INDIRB": Op.IGNORE,
    "INDIRF4": Op.LOAD4,
    "INDIRI4": Op.LOAD4,
    "INDIRP4": Op.LOAD4,
    "INDIRU4": Op.LOAD4,
    "INDIRI2": Op.LOAD2,
    "INDIRU2": Op.LOAD2,
    "INDIRI1": Op.LOAD1,
    "INDIRU1": Op.LOAD1,
    "CVFF4": Op.UNDEF,
    "CVFI4": Op.CVFI,
    "CVIF4": Op.CVIF,
    "CVII4": Op.SEX8,
    "CVII1": Op.IGNORE,
    "CVII2": Op.IGNORE,
    "CVIU4": Op.IGNORE,
    "CVPU4": Op.IGNORE,
    "CVUI4": Op.IGNORE,
    "CVUP4": Op.IGNORE,
    "CVUU4": Op.IGNORE,
    "CVUU1": Op.IGNORE,
    "NEGF4": Op.NEGF,
    "NEGI4": Op.NEGI,
    "ADDRGP4": Op.CONST,
    "ADDF4": Op.ADDF,
    "ADDI4": Op.ADD,
    "ADDP4": Op.ADD,
    "ADDP": Op.ADD,
    "ADDU4": Op.ADD,
    "SUBF4": Op.SUBF,
    "SUBI4": Op.SUB,
    "SUBP4": Op.SUB,
    "SUBU4": Op.SUB,
    "LSHI4": Op.LSH,
    "LSHU4": Op.LSH,
    "MODI4": Op.MODI,
    "MODU4": Op.MODU,
    "RSHI4": Op.RSHI,
    "RSHU4": Op.RSHU,
    "BANDI4": Op.BAND,
    "BANDU4": Op.BAND,
    "BCOMI4": Op.BCOM,
    "BCOMU4": Op.BCOM,
    "BORI4": Op.BOR,
    "BORU4": Op.BOR,
    "BXORI4": Op.BXOR,
    "BXORU4": Op.BXOR,
    "DIVF4": Op.DIVF,
    "DIVI4": Op.DIVI,
    "DIVU4": Op.DIVU,
    "MULF4": Op.MULF,
    "MULI4": Op.MULI,
    "MULU4": Op.MULU,
    "EQF4": Op.EQF,
    "EQI4": Op.EQ,
    "EQU4": Op.EQ,
    "GEF4": Op.GEF,
    "GEI4": Op.GEI,
    "GEU4": Op.GEU,
    "GTF4": Op.GTF,
    "GTI4": Op.GTI,
    "GTU4": Op.GTU,
    "LEF4": Op.LEF,
    "LEI4": Op.LEI,
    "LEU4": Op.LEU,
    "LTF4": Op.LTF,
    "LTI4": Op.LTI,
    "LTU4": Op.LTU,
    "NEF4": Op.NEF,
    "NEI4": Op.NE,
    "NEU4": Op.NE,
    "JUMPV": Op.JUMP,
    "LOADB4": Op.UNDEF,
    "LOADF4": Op.UNDEF,
    "LOADI4": Op.UNDEF,
    "LOADP4": Op.UNDEF,
    "LOADU4": Op.UNDEF,
}


class Segment:
    def __init__(self, image=None, segment_base=0):
        self.image = image or bytearray()
        self.segment_base = segment_base


class Symbol:
    def __init__(self, segment, value):
        self.segment = segment
        self.value = value


class AssemblerError(Exception):
    pass


class Assembler:
    def define_symbol(self, name, value):
        if self.pass_number == 1:
            return

        if name in self.symbols:
            raise AssemblerError(f"Multiple definitions for {name}")

        if name.startswith("$"):
            name += f"_{self.current_file_index}"

        self.symbols[name] = Symbol(self.current_segment, value)
        self.last_symbol = self.symbols[name]

    def lookup_symbol(self, name):
        if self.pass_number == 0:
            return 0

        if name.startswith("$"):
            name += f"_{self.current_file_index}"

        if name not in self.symbols:
            raise AssemblerError(f"Symbol {name} undefined")

        s = self.symbols[name]
        return s.segment.segment_base + s.value

    def parse_expression(self, expr):
        start = 0
        last_op = None
        for i in range(len(expr) + 1):
            if i == len(expr) or expr[i] == "+" or (expr[i] == "-" and i > 0):
                end = i
                sym = expr[start:end]
                start = end + 1

                if last_op == "+":
                    value += int(sym)
                elif last_op == "-":
                    value -= int(sym)
                else:
                    if sym[0] in "+-0123456789":
                        value = int(sym)
                    else:
                        value = self.lookup_symbol(sym)

                if i < len(expr):
                    last_op = expr[end]

        return value

    def hack_to_segment(self, segment):
        if self.current_segment != segment:
            self.current_segment = segment
            if self.pass_number == 0:
                self.last_symbol.segment = self.current_segment
                self.last_symbol.value = len(current_segment.image)

    def assemble(self, input_files, code_base=0, data_base=0, symbols={}):
        self.segments = {name: Segment() for name in ("code", "data", "lit", "bss")}
        data = self.segments["data"]
        lit = self.segments["lit"]
        bss = self.segments["bss"]

        self.symbols = {}

        # provided symbols should be relative to 0, no matter what code_base
        # and data_base are
        fake_segment = Segment()
        for sym, value in symbols.items():
            self.symbols[sym] = Symbol(fake_segment, value)

        self.current_args = 0
        self.current_locals = 0
        self.current_arg_offset = 0
        for pass_number in range(2):
            self.pass_number = pass_number
            data.segment_base = data_base
            lit.segment_base = data_base + len(data.image)
            bss.segment_base = lit.segment_base + len(lit.image)
            for seg in self.segments:
                self.segments[seg].image = bytearray()
            data.image = bytearray(b"\x00" * 4)

            instructions = []

            for current_file_index, filename in enumerate(input_files):
                self.current_file_index = current_file_index
                with open(filename) as f:
                    for line in f:
                        instructions.extend(
                            self._assemble_line(
                                line, address=code_base + len(instructions)
                            )
                        )

            for seg in self.segments:
                self.segments[seg].image = pad(self.segments[seg].image, 4)

        # convert symbol values to their actual addresses
        symbols = {
            name: symbol.value + symbol.segment.segment_base
            for name, symbol in self.symbols.items()
        }

        return instructions, self.segments, symbols

    def _assemble_line(self, line, address):
        tokens = line.split()
        if len(tokens) == 0:
            return []

        if tokens[0] in opcode_map:
            opcode = opcode_map[tokens[0]]

            if opcode == Op.UNDEF:
                raise AssemblerError(f"Undefined opcode: {opcode}")

            if opcode == Op.IGNORE:
                return []

            if opcode == Op.SEX8:
                # sign extensions need to check next parm
                if tokens[1][0] == "1":
                    opcode = Op.SEX8
                elif tokens[1][0] == "2":
                    opcode = Op.SEX16
                else:
                    raise AssemblerError(f"Bad sign extension: {tokens[1]}")
                # get rid of the parm now that we have the right opcode
                tokens = tokens[:1]

            if len(tokens) >= 2 and opcode not in (Op.CVIF, Op.CVFI):
                operand = self.parse_expression(tokens[1])
                if opcode == Op.BLOCK_COPY:
                    operand = align(expression, 4)
            else:
                operand = None

            return [Ins(opcode, operand)]

        elif tokens[0].startswith("CALL"):
            self.current_arg_offset = 0
            return [Ins(Op.CALL)]

        elif tokens[0].startswith("ARG"):
            self.current_arg_offset += 4
            return [Ins(Op.ARG, 8 + self.current_arg_offset - 4)]

        elif tokens[0].startswith("RET"):
            return [Ins(Op.LEAVE, 8 + self.current_locals + self.current_args)]

        elif tokens[0].startswith("pop"):
            return [Ins(Op.POP)]

        elif tokens[0].startswith("ADDRF"):
            offset = self.parse_expression(tokens[1])
            offset += 16 + self.current_args + self.current_locals
            return [Ins(Op.LOCAL, offset)]

        elif tokens[0].startswith("ADDRL"):
            offset = self.parse_expression(tokens[1]) + 8 + self.current_args
            return [Ins(Op.LOCAL, offset)]

        elif tokens[0] == "proc":
            self.define_symbol(tokens[1], address)
            self.current_locals = align(int(tokens[2]), 4)
            self.current_args = align(int(tokens[3]), 4)
            return [Ins(Op.ENTER, 8 + self.current_locals + self.current_args)]

        elif tokens[0] == "endproc":
            return [
                Ins(Op.PUSH),
                Ins(Op.LEAVE, 8 + self.current_locals + self.current_args),
            ]

        elif tokens[0] == "address":
            value = self.parse_expression(tokens[1])
            self.hack_to_segment(self.segments["data"])
            emit_int(self.current_segment, value)

        elif tokens[0] in self.segments:
            self.current_segment = self.segments[tokens[0]]

        elif tokens[0] == "equ":
            self.define_symbol(tokens[1], int(tokens[2]))

        elif tokens[0] == "align":
            alignment = int(tokens[1])
            self.current_segment.image = pad(self.current_segment.image, alignment)

        elif tokens[0] == "skip":
            size = int(tokens[1])
            self.current_segment.image += b"\x00" * size

        elif tokens[0] == "byte":
            size = int(tokens[1])
            value = int(tokens[2])
            if size == 1:
                self.hack_to_segment(self.segments["lit"])
            elif size == 4:
                self.hack_to_segment(self.segments["data"])
            self.current_segment.image += value.to_bytes(size, "little")

        elif tokens[0].startswith("LABEL"):
            if self.current_segment == self.segments["code"]:
                self.define_symbol(tokens[1], address)
            else:
                self.define_symbol(tokens[1], len(self.current_segment.image))

        elif tokens[0] in ("import", "export", "line", "file"):
            pass

        elif tokens[0].startswith(";"):
            pass

        else:
            raise AssemblerError(f"Syntax error: {line}")

        return []

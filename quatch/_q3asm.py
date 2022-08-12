# Copyright 1999-2005 Id Software, Inc.
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

from ._instruction import Instruction as Ins, Opcode as Op
from ._util import align, pad

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
    def __init__(self, segment, value, type):
        self.segment = segment
        self.value = value
        self.type = type


class AssemblerError(Exception):
    pass


class Assembler:
    def __init__(self, suppress_missing_symbols):
        self.suppress_missing_symbols = suppress_missing_symbols

    def my_assemble(
        self,
        input_files,
        symbols={},
    ):
        self.symbols = {}

        self.file = "unknown"
        self.line = 0

        # provided symbols should be relative to 0, no matter what code_base
        # and data_base are
        fake_segment = Segment()
        for name, sym in symbols.items():
            self.symbols[name] = Symbol(fake_segment, sym["value"], sym["type"])

        self.current_args = 0
        self.current_locals = 0
        self.current_arg_offset = 0
        rets = []
        for pass_number in range(2):
            self.pass_number = pass_number
            self.segments = {name: Segment() for name in ("code", "data", "lit", "bss")}
            for current_file_index, (filename, *base_map) in enumerate(input_files):
                base_map = base_map[0] if base_map else {}

                # clear segments, otherwise we keep appending the same dict
                # TODO solve this in a better way or something
                old_segs = self.segments
                self.segments = {}

                for section in ("code", "data", "lit", "bss"):
                    if f"{section}_base" in base_map:
                        segment_base = base_map[f"{section}_base"]
                        self.segments[section] = Segment(segment_base=segment_base)
                        if section == "data" and segment_base == 0:
                            # q3asm reserves address 0 for nullptrs
                            self.segments[section].image += b"\x00\x00\x00\x00"
                    else:
                        seg = old_segs[section]
                        self.segments[section] = Segment(
                            segment_base=seg.segment_base + len(seg.image)
                        )
                self.segments["code"].image = []  # TODO idk
                self.current_file_index = current_file_index
                self.comments = []
                with open(filename) as f:
                    for line in f:
                        self.segments["code"].image.extend(self._assemble_line(line))
                if pass_number == 1:
                    rets.append(self.segments)

        # convert symbol values to their actual addresses
        symbols = {
            name: {
                "value": symbol.value + symbol.segment.segment_base,
                "type": symbol.type,
            }
            for name, symbol in self.symbols.items()
        }
        return rets, symbols

    def assemble(
        self,
        input_files,
        code_base=0,
        data_base=0,
        lit_base=None,
        bss_base=None,
        pad_segments=True,
        symbols={},
    ):
        self.segments = {name: Segment() for name in ("code", "data", "lit", "bss")}
        data = self.segments["data"]
        lit = self.segments["lit"]
        bss = self.segments["bss"]

        self.symbols = {}

        self.file = "unknown"
        self.line = 0

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
            lit.segment_base = (
                lit_base if lit_base is not None else data_base + len(data.image)
            )
            bss.segment_base = (
                bss_base if bss_base is not None else lit.segment_base + len(lit.image)
            )
            for seg in self.segments:
                self.segments[seg].image = bytearray()

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

            if pad_segments:
                for seg in self.segments:
                    self.segments[seg].image = pad(self.segments[seg].image, 4)

        # convert symbol values to their actual addresses
        symbols = {
            name: symbol.value + symbol.segment.segment_base
            for name, symbol in self.symbols.items()
        }

        return instructions, self.segments, symbols

    def get_debug_info(self):
        debug_info = "".join(self.comments)
        self.comments = []
        return debug_info

    def _assemble_line(self, line):
        address = len(self.segments["code"].image)  # TODO idk
        tokens = line.split()
        if len(tokens) == 0:
            return []

        if tokens[0] in opcode_map:
            opcode = opcode_map[tokens[0]]

            if opcode == Op.UNDEF:
                self._error(f"undefined opcode {opcode}")

            if opcode == Op.IGNORE:
                return []

            if opcode == Op.SEX8:
                # sign extensions need to check next parm
                if tokens[1][0] == "1":
                    opcode = Op.SEX8
                elif tokens[1][0] == "2":
                    opcode = Op.SEX16
                else:
                    self._error(f"bad sign extension {tokens[1]}")
                # get rid of the parm now that we have the right opcode
                tokens = tokens[:1]

            if len(tokens) >= 2 and opcode not in (Op.CVIF, Op.CVFI):
                operand = self._parse_expression(tokens[1])
                if opcode == Op.BLOCK_COPY:
                    operand = align(operand, 4)
            else:
                operand = None

            return [Ins(opcode, operand, debug_info=self.get_debug_info())]

        elif tokens[0].startswith("CALL"):
            self.current_arg_offset = 0
            return [Ins(Op.CALL, debug_info=self.get_debug_info())]

        elif tokens[0].startswith("ARG"):
            self.current_arg_offset += 4
            return [
                Ins(
                    Op.ARG,
                    8 + self.current_arg_offset - 4,
                    debug_info=self.get_debug_info(),
                )
            ]

        elif tokens[0].startswith("RET"):
            return [
                Ins(
                    Op.LEAVE,
                    8 + self.current_locals + self.current_args,
                    debug_info=self.get_debug_info(),
                )
            ]

        elif tokens[0].startswith("pop"):
            return [Ins(Op.POP, debug_info=self.get_debug_info())]

        elif tokens[0].startswith("ADDRF"):
            offset = self._parse_expression(tokens[1])
            offset += 16 + self.current_args + self.current_locals
            return [Ins(Op.LOCAL, offset, debug_info=self.get_debug_info())]

        elif tokens[0].startswith("ADDRL"):
            offset = self._parse_expression(tokens[1]) + 8 + self.current_args
            return [Ins(Op.LOCAL, offset, debug_info=self.get_debug_info())]

        elif tokens[0] == "proc":
            self._define_symbol(tokens[1], address)
            self.current_locals = align(int(tokens[2]), 4)
            self.current_args = align(int(tokens[3]), 4)
            return [
                Ins(
                    Op.ENTER,
                    8 + self.current_locals + self.current_args,
                    debug_info=self.get_debug_info(),
                )
            ]

        elif tokens[0] == "endproc":
            return [
                Ins(Op.PUSH, debug_info=self.get_debug_info()),
                Ins(
                    Op.LEAVE,
                    8 + self.current_locals + self.current_args,
                    debug_info=self.get_debug_info(),
                ),
            ]

        elif tokens[0] == "address":
            value = self._parse_expression(tokens[1])
            self._hack_to_segment(self.segments["data"])
            self.current_segment.image += value.to_bytes(4, "little")

        elif tokens[0] in self.segments:
            self.current_segment = self.segments[tokens[0]]

        elif tokens[0] == "equ":
            self._define_symbol(tokens[1], int(tokens[2]))

        elif tokens[0] == "align":
            alignment = int(tokens[1])
            x = self.current_segment.segment_base + len(self.current_segment.image)
            x = align(x, alignment) - x
            self.current_segment.image.extend([0] * x)

        elif tokens[0] == "skip":
            size = int(tokens[1])
            self.current_segment.image += b"\x00" * size

        elif tokens[0] == "byte":
            size = int(tokens[1])
            value = int(tokens[2])
            if size == 1:
                self._hack_to_segment(self.segments["lit"])
            elif size == 4:
                self._hack_to_segment(self.segments["data"])
            self.current_segment.image += value.to_bytes(
                size, "little", signed=(value < 0)
            )

        elif tokens[0].startswith("LABEL"):
            if self.current_segment == self.segments["code"]:
                self._define_symbol(tokens[1], address)
            else:
                self._define_symbol(tokens[1], len(self.current_segment.image))

        elif tokens[0] == "file":
            self.file = tokens[1][1:-1]

        elif tokens[0] == "line":
            self.line = int(tokens[1])

        elif tokens[0] in ("import", "export", "line", "file"):
            pass

        elif tokens[0].startswith(";"):
            comment = line[1:]
            self.comments.append(comment[comment.index(":") + 1 :])

        else:
            self._error("syntax error")

        return []

    def _parse_expression(self, expr):
        start = 0
        last_op = None
        value = 0
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
                        value = self._lookup_symbol(sym)

                if i < len(expr):
                    last_op = expr[end]

        return value

    def _define_symbol(self, name, value):
        if self.pass_number == 1:
            return

        if name in self.symbols:
            self._error(f"multiple definitions for {name}")

        if name.startswith("$"):
            name += f"_{self.current_file_index}"

        self.symbols[name] = Symbol(
            self.current_segment,
            value,
            "code" if self.current_segment == self.segments["code"] else "data",
        )
        self.last_symbol = self.symbols[name]

    def _lookup_symbol(self, name):
        if self.pass_number == 0:
            return 0

        if name.startswith("$"):
            name += f"_{self.current_file_index}"

        if name not in self.symbols:
            if self.suppress_missing_symbols:
                return 0xC0DEDA7A
            self._error(f"symbol {name} undefined")

        s = self.symbols[name]
        return s.segment.segment_base + s.value

    def _hack_to_segment(self, segment):
        if self.current_segment != segment:
            self.current_segment = segment
            if self.pass_number == 0:
                self.last_symbol.segment = self.current_segment
                self.last_symbol.value = len(self.current_segment.image)

    def _error(self, message):
        raise AssemblerError(f"{self.file}:{self.line}: error; {message}")

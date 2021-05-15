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

"""This module provides a bytearray-like representation of a Qvm's memory."""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from enum import auto, Enum
from typing import overload, Optional
from .util import align


class Memory:
    """A Qvm's initial memory contents.

    This class behaves much like a bytearray, but every byte has an associated
    `RegionTag` that determines how it will be initialized. Because of this, appending
    data is done with `add_data` or `add_bss` instead of the usual append or extend
    methods.
    """

    def __init__(self) -> None:
        """Initialize an empty Memory."""
        self._regions: list[Region] = []
        self._size = 0

    @overload
    def __getitem__(self, key: int) -> int:
        ...

    @overload
    def __getitem__(self, key: slice) -> bytearray:
        ...

    def __getitem__(self, key):
        """Return self[key]."""
        if isinstance(key, int):
            if key < 0:
                key += len(self)
            if not 0 <= key < len(self):
                raise IndexError("Memory index out of range")

            region = self.region_at(key)
            if region is None:
                return 0
            else:
                return region.contents[key - region.begin]

        elif isinstance(key, slice):
            key = slice(*key.indices(len(self)))
            if key.step != 1:
                raise IndexError("Memory slices do not support step")

            result = bytearray()
            position = key.start
            for region in self.regions_overlapping(key.start, key.stop):
                # anything not covered by a region is BSS
                result.extend(b"\x00" * (region.begin - position))
                position = region.end

                begin = max(0, key.start - region.begin)
                end = region.size - max(0, (region.end - key.stop))
                result.extend(region.contents[begin:end])

            result.extend(b"\x00" * (key.stop - position))
            return result

        else:
            raise TypeError("Memory indices must be integers or slices")

    @overload
    def __setitem__(self, key: int, value: int) -> None:
        ...

    @overload
    def __setitem__(self, key: slice, value: bytes) -> None:
        ...

    def __setitem__(self, key, value):
        """Set self[key] to value.

        Raises ValueError if key includes any BSS regions or if value does not have the
        same size as the region being assigned to.
        """
        if isinstance(key, int):
            if key < 0:
                key += len(self)
            if not 0 <= key < len(self):
                raise IndexError("Memory index out of range")

            region = self.region_at(key)
            if region is None:
                raise IndexError("cannot assign to BSS region")
            else:
                region.contents[key - region.begin] = value

        elif isinstance(key, slice):
            key = slice(*key.indices(len(self)))
            if key.step != 1:
                raise IndexError("Memory slices do not support step")

            if max(0, key.stop - key.start) != len(value):
                raise ValueError("value must have same size as slice")

            regions = self.regions_overlapping(key.start, key.stop)
            contains_bss = False

            # check for gaps between key.start and key.stop
            position = key.start
            for region in regions:
                if region.begin > position:
                    break
                position = region.end

            if position < key.stop:
                contains_bss = True

            # if there were no regions found and the slice isn't empty then the whole
            # thing is bss
            if len(regions) == 0 and key.start < key.stop:
                contains_bss = True

            if contains_bss:
                raise IndexError("cannot assign to BSS regions")

            for region in regions:
                src_begin = max(0, region.begin - key.start)
                src_end = min(len(value), region.end - key.start)
                dst_begin = max(0, key.start - region.begin)
                dst_end = min(region.size, key.stop - region.begin)
                region.contents[dst_begin:dst_end] = value[src_begin:src_end]

        else:
            raise TypeError("Memory indices must be integers or slices")

    def __len__(self) -> int:
        """Return len(self)."""
        return self._size

    def add_region(self, tag: RegionTag, data: bytes, alignment: int = 1) -> int:
        """Add a new region of memory.

        DATA regions are meant hold to 4-byte words, so alignment and the size of data
        must both be multiples of 4 if tag is `DATA`.

        BSS regions are meant to hold zero-initialized data, so data must be all zeros
        if tag is `BSS`.

        Args:
            tag: The type of region to add.
            data: The data to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        self.align(alignment)
        address = len(self)

        if tag == RegionTag.BSS:
            if any(byte != 0 for byte in data):
                raise ValueError("BSS bytes must be zero")
            self._size += len(data)
        else:
            if tag == RegionTag.DATA and (len(data) % 4 != 0 or alignment % 4 != 0):
                raise ValueError("DATA regions must be at least 4-byte aligned")

            self._regions.append(
                Region(self._size, self._size + len(data), tag, bytearray(data))
            )
            self._size += len(data)

        return address

    def add_data(self, data: bytes, alignment: int = 4) -> int:
        """Add a `DATA` region.

        DATA regions are meant hold to 4-byte words, so alignment and the size of data
        must both be multiples of 4.

        Args:
            data: The data to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        return self.add_region(RegionTag.DATA, data, alignment)

    def add_lit(self, data: bytes, alignment: int = 1) -> int:
        """Add a `LIT` region.

        Args:
            data: The data to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        return self.add_region(RegionTag.LIT, data, alignment)

    def add_bss(self, size: int, alignment: int = 1) -> int:
        """Add a `BSS` region.

        Args:
            size: The number of BSS bytes to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        if size < 0:
            raise ValueError("size must be non-negative")
        self.align(alignment)
        address = len(self)
        self._size += size
        return address

    def align(self, alignment: int) -> None:
        """Pad with with zeros to a multiple of the given alignment.

        Does nothing if len(self) is already a multiple of alignment.

        Args:
            alignment: The requested alignment.
        """
        self._size = align(self._size, alignment)

    def regions_with_tag(self, tag: RegionTag) -> Iterator[Region]:
        """Find non-BSS regions with a given tag.

        If tag is `BSS` no regions will be found.

        Args:
            tag: The tag of the regions to find.

        Returns:
            An iterator over all regions with the given tag.
        """
        for region in self._regions:
            if region.tag == tag:
                yield region

    def region_at(self, point: int) -> Optional[Region]:
        """Find the `Region` overlapping a point.

        Args:
            point: The point the region must overlap.

        Returns:
            The region if it exists, otherwise None.
        """
        regions = self.regions_overlapping(point, point + 1)
        if len(regions) == 0:
            return None
        assert len(regions) == 1  # we shouldn't have created any overlaps
        return regions[0]

    def regions_overlapping(self, begin: int, end: int) -> list[Region]:
        """Find every `Region` that overlaps the interval [begin, end).

        Args:
            begin: The inclusive left bound of the interval.
            end: The exclusive right bound of the interval.

        Returns:
            All regions that overlap [begin, end).
        """
        query = Region(begin, end)
        first = max(bisect.bisect_left(self._regions, query), 0)
        last = min(bisect.bisect_right(self._regions, query), len(self._regions))
        return self._regions[first:last]


class RegionTag(Enum):
    """The type of data stored in a region of memory.

    * DATA bytes are initialized as 32-bit values and may be byte-swapped depending on
      the endianness of the interpreter.
    * LIT bytes are initialized as-is.
    * BSS bytes are initialized to zero and cannot be assigned to.
    """

    DATA = auto()
    LIT = auto()
    BSS = auto()


class Region:
    """A region of consecutive bytes with the same tag.

    Attributes:
        begin: The inclusive left bound of the region.
        end: The exclusive right bound of the region.
        tag: The type of data stored in the region.
        contents: The data stored in the region.
        size: The size of the region.
    """

    def __init__(
        self,
        begin: int,
        end: int,
        tag: Optional[RegionTag] = None,
        contents: Optional[bytes] = None,
    ) -> None:
        """Initialize a region covering [begin, end) with the given tag and contents."""
        self.begin = begin
        self.end = end
        self.tag = tag
        self.contents = contents

    def __lt__(self, other: Region) -> bool:
        """Return True if self is to the left of other."""
        return self.end <= other.begin

    def __gt__(self, other: Region) -> bool:
        """Return True if self is to the right of other."""
        return self.begin >= other.end

    @property
    def size(self) -> int:
        return self.end - self.begin

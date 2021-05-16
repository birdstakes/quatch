import unittest
from quatch.memory import Memory, RegionTag


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.memory = Memory()
        self.reference = bytearray()

        regions = (
            (RegionTag.BSS, b"\x00" * 10),
            (RegionTag.LIT, b"A" * 10),
            (RegionTag.LIT, b"B" * 2),
            (RegionTag.BSS, b"\x00" * 3),
            (RegionTag.LIT, b"C" * 4),
            (RegionTag.BSS, b"\x00" * 5),
            (RegionTag.LIT, b"D"),
        )

        for tag, data in regions:
            self.memory.add_region(tag, data=data)
            self.reference.extend(data)

    def test_getitem(self):
        size = len(self.reference)

        for i in range(-size * 2, size * 2):
            if -size <= i < size:
                self.assertEqual(self.reference[i], self.memory[i])
            else:
                with self.assertRaises(IndexError):
                    self.reference[i]
                with self.assertRaises(IndexError):
                    self.memory[i]

        for i in range(-size * 2, size * 2):
            for j in range(-size * 2, size * 2):
                self.assertEqual(self.reference[i:j], self.memory[i:j])

    def test_setitem(self):
        size = len(self.reference)

        for i in range(-size * 2, size * 2):
            if -size <= i < size:
                value = i % 254 + 1
                try:
                    self.memory[i] = value
                except IndexError:
                    # make sure there was actually a BSS region at self.memory[i]
                    self.assertTrue(self.reference[i] == 0)
                    continue
                self.reference[i] = value
                self.assertEqual(self.reference[i], self.memory[i])
            else:
                with self.assertRaises(IndexError):
                    self.reference[i]
                with self.assertRaises(IndexError):
                    self.memory[i]

        for i in range(-size * 2, size * 2):
            for j in range(-size * 2, size * 2):
                begin, end, _ = slice(i, j).indices(size)
                data = bytes([(i + j) % 254 + 1] * max(end - begin, 0))

                try:
                    self.memory[i:j] = data
                except IndexError:
                    # make sure there was actually a BSS region in self.memory[i:j]
                    self.assertTrue(any(byte == 0 for byte in self.reference[i:j]))
                    continue

                self.reference[i:j] = data
                self.assertEqual(self.reference[i:j], self.memory[i:j])


if __name__ == "__main__":
    unittest.main()

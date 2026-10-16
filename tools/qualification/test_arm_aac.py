"""Opt-in exact-instruction audio continuation qualification.

ARM_AAC_REPORT names a verified target build report. ARM_AAC_ADTS names an
existing/extracted AAC-LC stream. No files are published and no device changes.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest

from tools.qualification.arm_aac import ArmAAC, adts_packets


class ADTSBounds(unittest.TestCase):
    def test_empty_and_truncated_inputs(self):
        for data in (b'', b'\xff\xf1', b'\xff\xf1\x50\x80\x10\x1f\xfc'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                adts_packets(data)


@unittest.skipUnless(all(os.environ.get(key) for key in ('ARM_AAC_REPORT', 'ARM_AAC_ADTS', 'ARM_AAC_ABI_MANIFEST')), 'Set ARM_AAC_REPORT, ARM_AAC_ADTS and ARM_AAC_ABI_MANIFEST')
class ExactInstructionContinuation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = os.environ['ARM_AAC_REPORT']
        cls.abi_manifest = os.environ['ARM_AAC_ABI_MANIFEST']
        cls.asc, cls.packets = adts_packets(Path(os.environ['ARM_AAC_ADTS']).read_bytes())
        if len(cls.packets) < 66:
            raise ValueError('At least 66 real access units required')
        cls.packets = cls.packets[:66]
        report = json.loads(Path(cls.report).read_text())
        subprocess.run([report['toolchain']['compiler']['path'], '--target=armv4t-none-eabi', '-mcpu=arm7tdmi', '-marm', '-ffreestanding', '-I.', '-fsyntax-only', 'tools/qualification/arm_aac_abi.c'], check=True, capture_output=True)
        decoder = cls.decoder()
        cls.reference = [decoder.decode(packet) for packet in cls.packets]
        cls.binding = decoder.binding
        print('ARM_AAC_BINDING=' + json.dumps(cls.binding, sort_keys=True), flush=True)

    @classmethod
    def decoder(cls):
        return ArmAAC(cls.report, cls.asc, abi_manifest=cls.abi_manifest)

    def test_fresh_decoder_exact_pcm(self):
        decoder = self.decoder()
        for index, packet in enumerate(self.packets):
            self.assertEqual(decoder.decode(packet), self.reference[index], index)

    def test_skip_then_one_full_predecessor(self):
        for boundary in (1, 2, 16, 32, 64):
            with self.subTest(boundary=boundary):
                decoder = self.decoder()
                for packet in self.packets[:boundary - 1]:
                    decoder.decode(packet, 'skip')
                decoder.decode(self.packets[boundary - 1], 'discard')
                for index in range(boundary, min(boundary + 2, len(self.packets))):
                    self.assertEqual(decoder.decode(self.packets[index]), self.reference[index], (boundary, index))

    def test_skipped_overlap_cannot_be_exposed(self):
        decoder = self.decoder()
        decoder.decode(self.packets[0], 'skip')
        with self.assertRaisesRegex(ValueError, 'rejected: -3'):
            decoder.decode(self.packets[1])

    def test_packet_bounds_leave_decoder_usable(self):
        decoder = self.decoder()
        for packet in (b'', b'\0' * 8192):
            with self.assertRaises(ValueError):
                decoder.decode(packet)
        self.assertEqual(decoder.decode(self.packets[0]), self.reference[0])

    def test_malformed_au_requires_fresh_initialization(self):
        decoder = self.decoder()
        with self.assertRaisesRegex(ValueError, 'rejected: -2'):
            decoder.decode(b'\xff')
        with self.assertRaisesRegex(ValueError, 'rejected: -2'):
            decoder.decode(self.packets[0])
        decoder.machine.mem_write(decoder.INPUT, self.asc)
        self.assertEqual(decoder.call('ln_aac_raw_init', decoder.DECODER, decoder.INPUT, len(self.asc)), 1)
        self.assertEqual(decoder.decode(self.packets[0]), self.reference[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)

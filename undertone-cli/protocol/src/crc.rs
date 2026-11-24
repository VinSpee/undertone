// SPDX-License-Identifier: GPL-3.0-only
//! The checksums and ciphers of the pedal's files and protocols: JieLi's CRC-16 and its 16-bit "ENC" stream
//! (tools/pocketx_fw.py), zlib's CRC-32 (the recovery mode's frames and the layouts' boot areas), and the cipher of the
//! chip key's answer (tools/uboot_rescue.py).

const fn crc16_table() -> [u16; 256] {
    let mut t = [0u16; 256];
    let mut i = 0;
    while i < 256 {
        let mut c = (i as u16) << 8;
        let mut k = 0;
        while k < 8 {
            c = if c & 0x8000 != 0 { (c << 1) ^ 0x1021 } else { c << 1 };
            k += 1;
        }
        t[i] = c;
        i += 1;
    }
    t
}

const CRC16: [u16; 256] = crc16_table();

/// CRC-16, polynomial 0x1021, from `crc` (0 for a fresh one): `pocketx_fw.crc16`.
pub fn crc16(data: &[u8], crc: u16) -> u16 {
    data.iter()
        .fold(crc, |crc, &b| (crc << 8) ^ CRC16[((crc >> 8) as u8 ^ b) as usize])
}

const fn crc32_table() -> [u32; 256] {
    let mut t = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut c = i as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 != 0 { (c >> 1) ^ 0xEDB8_8320 } else { c >> 1 };
            k += 1;
        }
        t[i] = c;
        i += 1;
    }
    t
}

const CRC32: [u32; 256] = crc32_table();

/// zlib's CRC-32 of `data`, continuing from `crc` (0 for a fresh one): `zlib.crc32(data, crc)`.
pub fn crc32(data: &[u8], crc: u32) -> u32 {
    !data
        .iter()
        .fold(!crc, |c, &b| (c >> 8) ^ CRC32[((c as u8) ^ b) as usize])
}

/// JieLi's "ENC": each byte XOR the low byte of a 16-bit LFSR that starts at `key` (`pocketx_fw.enc`). Its own inverse.
pub fn enc(data: &[u8], mut key: u16) -> Vec<u8> {
    data.iter()
        .map(|&b| {
            let out = b ^ key as u8;
            key = (key << 1) ^ if key & 0x8000 != 0 { 0x1021 } else { 0 };
            out
        })
        .collect()
}

/// The chip key, 0x980F: the key of the app area's ENC and of the boot loader's checks.
pub const CHIP_KEY: u16 = 0x980F;

/// The app area's ENC: each 32-byte block under the chip key XOR its offset / 4 (`pocketx_fw.sfc`).
pub fn sfc(data: &[u8], base_rel: usize) -> Vec<u8> {
    data.chunks(32)
        .enumerate()
        .flat_map(|(i, block)| enc(block, CHIP_KEY ^ ((base_rel + i * 32) >> 2) as u16))
        .collect()
}

/// JieLi's "CrcDecode" of the chip key's answer (key 0xFFFF); the magic is "孟黎我爱你，玉林" in GB2312.
const MAGIC: [u8; 16] = [
    0xc3, 0xcf, 0xc0, 0xe8, 0xce, 0xd2, 0xb0, 0xae, 0xc4, 0xe3, 0xa3, 0xac, 0xd3, 0xf1, 0xc1, 0xd6,
];

/// `uboot_rescue.cipher`: its own inverse, like ENC.
pub fn cipher(data: &[u8]) -> Vec<u8> {
    let mut crc = crc16(&[0xFF, 0xFF], 0xFFFF);
    data.iter()
        .enumerate()
        .map(|(i, &b)| {
            crc = crc16(&MAGIC[i % 16..i % 16 + 1], crc);
            b ^ crc as u8
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc32_is_zlibs() {
        assert_eq!(crc32(b"", 0), 0);
        assert_eq!(crc32(b"123456789", 0), 0xCBF4_3926);
        assert_eq!(crc32(b"6789", crc32(b"12345", 0)), 0xCBF4_3926);
    }

    #[test]
    fn crc16_is_xmodems() {
        assert_eq!(crc16(b"123456789", 0), 0x31C3);
    }

    #[test]
    fn enc_and_cipher_undo_themselves() {
        let data: Vec<u8> = (0..100u8).collect();
        assert_eq!(enc(&enc(&data, 0x1234), 0x1234), data);
        assert_eq!(cipher(&cipher(&data)), data);
        assert_eq!(sfc(&sfc(&data, 64), 64), data);
    }
}

import struct

def hex_to_float(hex_value):
    # 1. Convert the integer (e.g., 0x000016C3) to 4 bytes
    #    We use 'big' here to preserve the order: 00, 00, 16, C3
    byte_data = hex_value.to_bytes(4, byteorder='big')
    
    # 2. Unpack the bytes as a Little-Endian float ('<f')
    #    '<' = Little-Endian
    #    'f' = standard 4-byte float (IEEE-754)
    result = struct.unpack('<f', byte_data)[0]
    
    return result

# Test Cases
# val1 = 0x2FF77B40
# val2 = 0xBC08FE3C
# val3 = 0x00005C3D

# print(f"Hex: 0x{val1:08X} -> Float: {hex_to_float(val1)}")
# print(f"Hex: 0x{val2:08X} -> Float: {hex_to_float(val2)}")
# print(f"Hex: 0x{val3:08X} -> Float: {hex_to_float(val3)}")
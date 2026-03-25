def parse_mapping_id_sn(mapping_str):
    #####parse the mapping string into a dictionary, the example string is as "#####
    #"calibration for Part Numbers: '1566', Serial Numbers: '1321321sd', CAN Addresses: 0x1"
    # the output dictionary is as {"part_numbers": ['1566'], "serial_numbers": ['1321321sd'], "can_msg_addresses": [0x1]}    
    mapping_dict = {}
    try:
        # Extract the part numbers
        part_numbers_str = mapping_str.split("Part Numbers:")[1].split(", Serial Numbers:")[0].strip()
        part_numbers = [pn.strip() for pn in part_numbers_str.split(",")]
        mapping_dict["part_numbers"] = part_numbers
    
        # Extract the serial numbers
        serial_numbers_str = mapping_str.split("Serial Numbers:")[1].split(", CAN Addresses:")[0].strip()
        serial_numbers = [sn.strip() for sn in serial_numbers_str.split(",")]
        mapping_dict["serial_numbers"] = serial_numbers
    
        # Extract the CAN addresses
        can_addresses_str = mapping_str.split("CAN Addresses:")[1].strip()
        can_addresses = [int(addr.strip(), 16) for addr in can_addresses_str.split(",")]
        mapping_dict["can_msg_addresses"] = can_addresses
    except (IndexError, ValueError) as e:
        print(f"Error parsing mapping string: {e}")
    return mapping_dict


def get_sn_pn_by_id(mapping_dict, can_msg_id):
    #####get the corresponding part number and serial number based on the can message id, return as a tuple (part_number, serial_number)
    try:
        index = mapping_dict["can_msg_addresses"].index(can_msg_id)
        part_number = mapping_dict["part_numbers"][index]
        serial_number = mapping_dict["serial_numbers"][index]
        return part_number, serial_number
    except ValueError as e:
        print(f"CAN message ID {can_msg_id} not found in mapping: {e}")
        return None, None
    

if __name__ == "__main__":
    test_mapping_str = "calibration for Part Numbers: '1566', Serial Numbers: '1321321sd', CAN Addresses: 0x1"
    mapping_dict = parse_mapping_id_sn(test_mapping_str)
    print(mapping_dict)
    part_number, serial_number = get_sn_pn_by_id(mapping_dict, 0x1)
    print(f"Part Number: {part_number}, Serial Number: {serial_number}")
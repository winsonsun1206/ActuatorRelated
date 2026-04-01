import json
from pathlib import Path

def parse_test_cases(file_path):
    """
    Parses a JSON test sequence file and extracts the test cases.
    """
    try:
        # Open and load the JSON file
        with open(file_path, 'r') as file:
            data = json.load(file)
            
        # Extract the 'test_cases' list. 
        # Using .get() ensures it returns an empty list if the key is missing.
        test_cases = data.get("test_cases", [])
        
        # Display summary info
        dut_model = data.get("DUT", {}).get("model", "Unknown")
        print(f"--- Loaded test sequence for DUT Model: {dut_model} ---")
        print(f"--- Found {len(test_cases)} test cases. ---\n")
        
        # Iterate through the list of test cases
        for index, test_case in enumerate(test_cases, start=1):
            test_id = test_case.get("id")
            test_name = test_case.get("name")
            description = test_case.get("description")
            parameters = test_case.get("parameters", {})
            
            print(f"Test Case {index}: {test_id}. Name: {test_name}. loaded successfully. Description: {description}")
            print("-" * 40)

        dut_info = data.get("DUT", {})
            
        
        
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: The file '{file_path}' does not contain valid JSON format.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print(f"Finished parsing the test sequence file: {file_path}")
        return test_cases, dut_info

# ==========================================
# Example usage
# ==========================================
if __name__ == "__main__":
    # Make sure 'test_sequence.json' is in the same directory as this script
    my_test_cases, dut_info= parse_test_cases(f'{Path.home()}/ActuatorRelated/ActuatorTest/ActuatorTestDemo/resource/sequences/test_sequence_20.json')
    if my_test_cases is not None and len(my_test_cases)>0:
        for test in my_test_cases:
            print(test)
            print("-"*40)
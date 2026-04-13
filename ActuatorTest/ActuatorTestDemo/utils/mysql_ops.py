from contextlib import contextmanager
from utils.mysql_session import get_db_session, session_maker
from utils.models import RuninTestRecord
import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '../secrets/.env')
load_dotenv(env_path)



@contextmanager
def db_session_manager():
    db = next(get_db_session())
    try:
        yield db
    finally:        
        pass



def insert_test_record(record: RuninTestRecord):
    
    with db_session_manager() as session:
        try:
            session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Error inserting record: {e}")
    

def update_test_record(serial_number: str, **kwargs):
    with db_session_manager() as session:
        try:
            record = session.query(RuninTestRecord).filter_by(serial_number=serial_number).first()
            if record:
                for key, value in kwargs.items():
                    setattr(record, key, value)
                session.commit()
            else:
                print(f"No record found with serial number: {serial_number}")
        except Exception as e:
            session.rollback()
            print(f"Error updating record: {e}")
        if record:
            for key, value in kwargs.items():
                setattr(record, key, value)
            session.commit()
        else:
            print(f"No record found with serial number: {serial_number}")
            
def get_test_record_by_sn(serial_number: str):
    with db_session_manager() as session:
        try:
            record = session.query(RuninTestRecord).filter_by(serial_number=serial_number).first()
            if not record:
                print(f"No record found with serial number: {serial_number}")
                return None
            print(f"Record found: {record.serial_number}, {record.part_number}, {record.joint_name},"
                  f" {record.test_time}, {record.can_id},{record.final_status}")
            return record
        except Exception as e:
            print(f"Error retrieving record: {e}")
            return None
        
def delete_test_record_by_sn(serial_number: str):
    with db_session_manager() as session:
        try:
            record = session.query(RuninTestRecord).filter_by(serial_number=serial_number).first()
            if record:
                session.delete(record)
                session.commit()
            else:
                print(f"No record found with serial number: {serial_number}")
        except Exception as e:
            session.rollback()
            print(f"Error deleting record: {e}")
            
            
if __name__ == "__main__":

    new_record = RuninTestRecord(
        serial_number="SN123456",
        joint_name="joint",
        part_number="PN123456",
        can_id=0x1,
        hw_version="1.0",
        sw_version="1.0",
        operator_id="OP001",
        operator_name="Alice",
        test_duration_sec=3600,
        calibration_result="Calibrated successfully",
        final_status="PASS",
        start_current_a=10.5,
        voltage_v=12.0,
        max_temp_c=75.0,
        current_shift=0.5,
        forward_viscosity=100.0,
        reverse_viscosity=120.0,
        performance_details={"torque": [10, 20, 30], "speed": [100, 200, 300]}
    )
    
    insert_test_record(new_record)
    
    update_test_record("SN123456", final_status="FAIL")
    
    print(get_test_record_by_sn("SN123456"))
    
    delete_test_record_by_sn("SN123456")
    deleted_record = get_test_record_by_sn("SN123456")
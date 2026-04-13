from sqlalchemy import create_engine, Column, Integer, String, DateTime,Float, Enum, JSON
from sqlalchemy.sql import func
from utils.mysql_session import Base

class RuninTestRecord(Base):
    __tablename__ = 'runin_test_records'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    serial_number = Column(String(100), nullable=False, unique=True)
    joint_name = Column(Enum('joint', 'wheel'), nullable=False)
    part_number = Column(String(50), nullable=False)
    can_id = Column(Integer)
    
    hw_version = Column(String(50))
    sw_version = Column(String(50))
    
    operator_id = Column(String(50))
    operator_name = Column(String(50))
    test_time = Column(DateTime, server_default=func.now())
    test_duration_sec = Column(Float)
    
    calibration_result = Column(String(100))
    error_code = Column(String(100), default='0x00')
    final_status = Column(Enum('PASS', 'FAIL'), nullable=False)
    
    start_current_a = Column(Float)
    voltage_v = Column(Float)
    max_temp_c = Column(Float)
    current_shift = Column(Float)
    forward_viscosity = Column(Float)
    reverse_viscosity = Column(Float)
    
    # SQLAlchemy handles the json.dumps() / json.loads() automatically
    performance_details = Column(JSON)
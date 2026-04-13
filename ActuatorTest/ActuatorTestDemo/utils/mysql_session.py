from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '../secrets/.env')
load_dotenv(env_path)

Base = declarative_base()

mysql_url_root = f'mysql+mysqlconnector://root:{os.getenv("mysql_root_password")}@{os.getenv("mysql_host")}:{os.getenv("mysql_port")}/{os.getenv("mysql_db_name")}'
mysql_url_user = f'mysql+mysqlconnector://{os.getenv("mysql_user")}:{os.getenv("mysql_user_password")}@{os.getenv("mysql_host")}:{os.getenv("mysql_port")}/{os.getenv("mysql_db_name")}'

engine = create_engine(mysql_url_root, echo=False)
session_maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db_session():
    db = session_maker()
    try:
        yield db
    finally:        
        db.close()
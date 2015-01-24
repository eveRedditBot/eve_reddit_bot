import os
import sys
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine
 
Base = declarative_base()


class Yaml(Base):
    __tablename__ = 'yaml'
    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)

engine = create_engine(os.environ['DATABASE_URL'])

Base.metadata.create_all(engine)

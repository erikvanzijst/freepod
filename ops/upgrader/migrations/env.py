from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from upgrader.db import Base, database_url

if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

with create_engine(database_url()).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

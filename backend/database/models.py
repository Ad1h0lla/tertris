from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Float,
    Text,
    Boolean,
    DateTime,
    JSON,
)

from sqlalchemy.orm import sessionmaker, declarative_base

from datetime import datetime
import os


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./executa.db"
)

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False
    } if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


class Execution(Base):
    __tablename__ = "executions"

    id = Column(
        String,
        primary_key=True
    )

    user_id = Column(String)

    original_idea = Column(Text)

    understood_goal = Column(Text)

    intent_classification = Column(JSON)

    idea_type = Column(String)

    recommended_phases = Column(JSON)

    status = Column(
        String,
        default="running"
    )

    current_phase = Column(
        Integer,
        default=1
    )

    phase_statuses = Column(
        JSON,
        nullable=True
    )

    phase_names = Column(
        JSON,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class PhaseResult(Base):
    __tablename__ = "phase_results"

    id = Column(
        String,
        primary_key=True
    )

    execution_id = Column(String)

    phase_number = Column(Integer)

    phase_name = Column(
        String,
        nullable=True
    )

    outcome_type = Column(String)

    outcome = Column(Text)

    validation_score = Column(Float)

    execution_trace = Column(JSON)

    status = Column(
        String,
        default="complete"
    )

    started_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    completed_at = Column(
        DateTime,
        nullable=True
    )

    approved_at = Column(
        DateTime,
        nullable=True
    )

    selected_agents = Column(
        JSON,
        nullable=True
    )

    verification_result = Column(
        JSON,
        nullable=True
    )

    simulation_result = Column(
        JSON,
        nullable=True
    )

    deployment_result = Column(
        JSON,
        nullable=True
    )

    review_result = Column(
        JSON,
        nullable=True
    )

    distribution_plan = Column(
        JSON,
        nullable=True
    )

    error_message = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(
        String,
        primary_key=True
    )

    user_id = Column(String)

    agent_type = Column(String)

    payload = Column(JSON)

    interval_hours = Column(Integer)

    notify_via = Column(
        String,
        default="none"
    )

    notify_target = Column(
        String,
        default=""
    )

    status = Column(
        String,
        default="active"
    )

    run_count = Column(
        Integer,
        default=0
    )

    last_run = Column(DateTime)

    next_run = Column(DateTime)

    last_result = Column(JSON)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class StoredCredential(Base):
    __tablename__ = "stored_credentials"

    id = Column(
        String,
        primary_key=True
    )

    user_id = Column(String)

    app_name = Column(String)

    credential_encrypted = Column(Text)

    connection_type = Column(
        String,
        default="api_key"
    )

    connected_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    last_used = Column(DateTime)

    is_active = Column(
        Boolean,
        default=True
    )

    display_name = Column(
        String,
        nullable=True
    )


class ConnectorAction(Base):
    __tablename__ = "connector_actions"

    id = Column(
        String,
        primary_key=True
    )

    user_id = Column(String)

    execution_id = Column(String)

    connector_id = Column(String)

    action = Column(String)

    status = Column(String)

    result = Column(JSON)

    error = Column(Text)

    executed_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class DistributionCampaign(Base):
    __tablename__ = "distribution_campaigns"

    id = Column(
        String,
        primary_key=True
    )

    execution_id = Column(
        String,
        index=True
    )

    user_id = Column(
        String,
        index=True
    )

    phase = Column(
        Integer,
        default=3
    )

    status = Column(
        String,
        default="PLANNED"
    )

    actions = Column(
        JSON,
        nullable=True
    )

    summary = Column(
        JSON,
        nullable=True
    )

    connector_requirements = Column(
        JSON,
        nullable=True
    )

    events = Column(
        JSON,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


def init_db():
    """Create all tables on startup and apply missing column migrations."""
    Base.metadata.create_all(
        bind=engine
    )

    from sqlalchemy import text
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE executions ADD COLUMN current_phase INTEGER DEFAULT 1;",
            "ALTER TABLE executions ADD COLUMN phase_statuses JSON;",
            "ALTER TABLE phase_results ADD COLUMN phase_name VARCHAR;",
            "ALTER TABLE phase_results ADD COLUMN started_at DATETIME;",
            "ALTER TABLE phase_results ADD COLUMN completed_at DATETIME;",
            "ALTER TABLE phase_results ADD COLUMN approved_at DATETIME;",
            "ALTER TABLE phase_results ADD COLUMN selected_agents JSON;",
            "ALTER TABLE phase_results ADD COLUMN verification_result JSON;",
            "ALTER TABLE phase_results ADD COLUMN simulation_result JSON;",
            "ALTER TABLE phase_results ADD COLUMN deployment_result JSON;",
            "ALTER TABLE phase_results ADD COLUMN review_result JSON;",
            "ALTER TABLE phase_results ADD COLUMN distribution_plan JSON;",
            "ALTER TABLE phase_results ADD COLUMN error_message TEXT;",
            "ALTER TABLE executions ADD COLUMN phase_names JSON;",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

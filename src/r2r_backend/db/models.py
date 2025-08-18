"""
SQLAlchemy models for R2R personalized bike routing system.
Designed for Supabase with RLS support.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    JSON,
    ForeignKey,
    DateTime,
    Text,
    Enum,
    UniqueConstraint,
    CheckConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


# Enums
class DisciplineType(str, PyEnum):
    """Bike discipline types"""
    ROAD = "road"
    GRAVEL = "gravel"
    MTB = "mtb"
    TREKKING = "trekking"
    COMMUTE = "commute"


class RequestStatus(str, PyEnum):
    """Status for parameter update requests"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def generate_uuid():
    """Generate a UUID4 string"""
    return str(uuid.uuid4())


class GraphHopperCustomProfile(Base):
    """
    Master templates for GraphHopper custom profiles.
    One per discipline, with versioning support for experimentation.
    """
    __tablename__ = "graphhopper_custom_profiles"

    id = Column(Integer, primary_key=True)
    discipline = Column(Enum(DisciplineType), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # The JSON template with placeholders like {parameter_name}
    template = Column(JSONB, nullable=False)

    # List of parameter names that appear in the template
    parameters = Column(JSONB, nullable=False)  # ["param1", "param2", ...]

    # Version control
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    template_hash = Column(String(64))  # SHA256 of template for change detection

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    priors = relationship("ProfilePrior", back_populates="profile", cascade="all, delete-orphan")
    user_profiles = relationship("UserProfile", back_populates="custom_profile")

    # Constraints
    __table_args__ = (
        UniqueConstraint('discipline', 'version', name='unique_discipline_version'),
        Index('idx_active_profiles', 'discipline', 'is_active'),
    )


class ProfilePrior(Base):
    """
    Default parameter values (priors) for each profile.
    Learned from Bayesian optimization on reference routes.
    """
    __tablename__ = "profile_priors"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("graphhopper_custom_profiles.id"), nullable=False)

    # Prior parameters as key-value pairs
    means = Column(JSONB, nullable=False)  # {"param1": 1.5, "param2": 0.8, ...}
    variances = Column(JSONB, nullable=False)  # {"param1": 0.01, "param2": 0.01, ...}


    # Metadata about how these priors were learned
    training_metadata = Column(JSONB)  # {"routes_used": 100, "convergence_metric": 0.95, ...}

    # Version control for priors
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    profile = relationship("GraphHopperCustomProfile", back_populates="priors")

    __table_args__ = (
        UniqueConstraint('profile_id', 'version', name='unique_profile_prior_version'),
    )


class UserProfile(Base):
    """
    User's access to specific discipline profiles.
    One entry per user per discipline they have access to.
    """
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to Supabase auth user
    user_id = Column(UUID(as_uuid=True), nullable=False)  # From auth.users

    # Link to master profile
    profile_id = Column(Integer, ForeignKey("graphhopper_custom_profiles.id"), nullable=False)

    # User's display name for this profile (e.g., "My Training Profile", "Scenic Routes")
    custom_name = Column(String(255))

    # Tracking
    last_parameter_update = Column(DateTime(timezone=True))
    total_ratings = Column(Integer, default=0, nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    custom_profile = relationship("GraphHopperCustomProfile", back_populates="user_profiles")
    learned_parameters = relationship("LearnedParameters", back_populates="user_profile",
                                      cascade="all, delete-orphan", order_by="LearnedParameters.created_at.desc()")
    ratings = relationship("SegmentRating", back_populates="user_profile", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('user_id', 'profile_id', name='unique_user_profile'),
        Index('idx_user_profiles_user', 'user_id'),
    )


class LearnedParameters(Base):
    """
    Versioned history of learned parameters for each user profile.
    New entry created each time parameters are updated.
    """
    __tablename__ = "learned_parameters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False)

    # The actual parameters
    parameters = Column(JSONB, nullable=False)  # {"param1": 1.2, "param2": 0.9, ...}

    # Track if this is the initial prior or learned from ratings
    is_prior = Column(Boolean, nullable=False, default=False)

    # Metrics about the learning
    rating_count_at_generation = Column(Integer)
    convergence_metrics = Column(JSONB)  # {"log_likelihood": -123.4, "rmse": 0.05, ...}

    # Computation details
    computation_time_ms = Column(Integer)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user_profile = relationship("UserProfile", back_populates="learned_parameters")

    __table_args__ = (
        Index('idx_learned_params_profile', 'user_profile_id'),
        Index('idx_learned_params_created', 'user_profile_id', 'created_at'),
    )


class OSMWay(Base):
    """
    Sparse table of OSM ways that have been rated.
    Only added when first rating is created.
    """
    __tablename__ = "osm_ways"

    id = Column(Integer, primary_key=True)
    osm_id = Column(String(50), nullable=False, unique=True)  # OSM way ID as string

    # Geometry (stored as WKT for simplicity in MVP)
    geometry_wkt = Column(Text, nullable=False)

    # Key attributes for display/context
    surface = Column(String(50))
    smoothness = Column(String(50))
    highway_class = Column(String(50))  # residential, primary, track, etc.
    track_type = Column(String(10))  # grade1-grade5 for tracks

    # Cached statistics
    length_meters = Column(Float)
    elevation_gain = Column(Float)

    # When this way was first added
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    ratings = relationship("SegmentRating", back_populates="osm_way", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_osm_way_id', 'osm_id'),
    )


class SegmentRating(Base):
    """
    User's rating for a specific OSM way segment.
    Weight-based system with reference scale.
    """
    __tablename__ = "segment_ratings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False)
    osm_way_id = Column(Integer, ForeignKey("osm_ways.id"), nullable=False)

    # The rating as a weight/multiplier (0.1 to 10, where 1.0 is reference)
    weight = Column(Float, nullable=False)

    # Optional context
    notes = Column(Text)  # User's notes about this rating
    conditions = Column(JSONB)  # {"weather": "dry", "time_of_day": "morning", ...}

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user_profile = relationship("UserProfile", back_populates="ratings")
    osm_way = relationship("OSMWay", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint('user_profile_id', 'osm_way_id', name='unique_user_way_rating'),
        CheckConstraint('weight > 0 AND weight <= 100', name='valid_weight_range'),
        Index('idx_ratings_user_profile', 'user_profile_id'),
        Index('idx_ratings_way', 'osm_way_id'),
    )


class ParameterUpdateRequest(Base):
    """
    Queue for parameter update requests.
    Processed asynchronously to recompute learned parameters.
    """
    __tablename__ = "parameter_update_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_profile_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False)

    # Request status
    status = Column(Enum(RequestStatus), nullable=False, default=RequestStatus.PENDING)

    # Processing details
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Error tracking
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # Result reference
    learned_parameters_id = Column(UUID(as_uuid=True))  # ID of created learned_parameters entry

    __table_args__ = (
        Index('idx_update_requests_status', 'status'),
        Index('idx_update_requests_user', 'user_profile_id'),
    )


class SavedRoute(Base):
    """
    User's saved routes for quick access.
    """
    __tablename__ = "saved_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)  # From auth.users

    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Route data
    geometry_wkt = Column(Text, nullable=False)  # LINESTRING WKT
    start_point = Column(JSONB, nullable=False)  # {"lat": 52.52, "lon": 13.405}
    end_point = Column(JSONB, nullable=False)

    # Route metadata
    distance_meters = Column(Float, nullable=False)
    elevation_gain = Column(Float)
    estimated_time_seconds = Column(Integer)

    # Which profile was used
    discipline = Column(Enum(DisciplineType))
    profile_settings = Column(JSONB)  # Snapshot of settings used

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index('idx_saved_routes_user', 'user_id'),
    )


class PrecomputedRoute(Base):
    """
    Curated/popular routes by location.
    Can be seeded or algorithmically generated.
    """
    __tablename__ = "precomputed_routes"

    id = Column(Integer, primary_key=True)

    name = Column(String(255), nullable=False)
    description = Column(Text)
    discipline = Column(Enum(DisciplineType), nullable=False)

    # Route data
    geometry_wkt = Column(Text, nullable=False)
    start_point = Column(JSONB, nullable=False)  # {"lat": 52.52, "lon": 13.405}
    end_point = Column(JSONB, nullable=False)

    # Location for spatial queries (could add PostGIS later)
    center_lat = Column(Float, nullable=False)
    center_lon = Column(Float, nullable=False)

    # Route characteristics
    distance_meters = Column(Float, nullable=False)
    elevation_gain = Column(Float)
    difficulty_rating = Column(Integer)  # 1-5

    # Popularity
    usage_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_precomputed_location', 'center_lat', 'center_lon'),
        Index('idx_precomputed_discipline', 'discipline'),
    )
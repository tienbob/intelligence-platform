"""
HR domain SQLAlchemy models — PLACEHOLDER.

Models to implement:
    - Candidate (profile, skills, experience, education)
    - Job (requirements, salary range, location, remote policy)
    - Skill (name, category, proficiency levels)
    - Application (candidate_id, job_id, status, scores)
    - SalaryBenchmark (role, location, percentiles)
    - Company (employer profile, culture indicators)
"""

from __future__ import annotations

# TODO: Define SQLAlchemy models for the HR domain.
# Use the same Base from app.core.database as the stock domain.
#
# Example structure:
#
# from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
# from app.core.database import Base
#
# class Candidate(Base):
#     __tablename__ = "hr_candidates"
#     id = Column(Integer, primary_key=True)
#     external_id = Column(String, unique=True, index=True)
#     name = Column(String)
#     email = Column(String)
#     skills = Column(JSON)        # [{"name": "Python", "level": "expert"}, ...]
#     experience_years = Column(Float)
#     education = Column(JSON)     # [{"degree": "MS", "field": "CS", "school": "MIT"}]
#     current_role = Column(String)
#     current_company = Column(String)
#     location = Column(String)
#     remote_preference = Column(String)
#     salary_expectation = Column(Float)
#     profile_data = Column(JSON)  # Full raw profile
#     created_at = Column(DateTime)
#     updated_at = Column(DateTime)

# Placeholder — no models defined yet
Candidate = None
Job = None
Skill = None
Application = None
SalaryBenchmark = None
Company = None
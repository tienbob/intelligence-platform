# frozen_string_literal: true

# Rails-owned junction granting a user visibility of a tracked company.
#
# Per docs/TABLE_OWNERSHIP.md this table is application-owned: the Rails
# gateway is the authoritative writer; Python only reads it to scope
# requests. Backing DDL lives in Alembic migration 0016_user_companies
# (companies.id is Python-domain data, so no Rails association is declared
# for it).
class UserCompany < ApplicationRecord
  self.table_name = "user_companies"

  belongs_to :user

  validates :company_id, presence: true

  # (user_id, company_id) carries a UNIQUE index in the database; concurrent
  # duplicate grants surface as ActiveRecord::RecordNotUnique.
end
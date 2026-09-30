class AddUserIdToAlerts < ActiveRecord::Migration[8.0]
  # Mirrors Python Alembic 0018 (shared DB, dual migration history).
  # Nullable: system/scheduler alerts stay NULL = visible to everyone;
  # user-created alerts carry the caller's user_id (audit F1/S2 — previously
  # every user could read and dismiss every alert).
  # No FK: the users table is Rails-owned but Python writes these rows.
  #
  # Idempotent: Alembic 0018 may already have added the column/index
  # (shared DB). `db:migrate` re-runs would otherwise abort with
  # PG::DuplicateColumn (same pattern as 20260810030000).
  def change
    add_column :alerts, :user_id, :bigint unless column_exists?(:alerts, :user_id)
    add_index :alerts, :user_id unless index_exists?(:alerts, :user_id)
  end
end

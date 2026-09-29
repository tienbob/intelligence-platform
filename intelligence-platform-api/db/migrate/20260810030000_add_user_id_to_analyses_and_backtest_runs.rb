class AddUserIdToAnalysesAndBacktestRuns < ActiveRecord::Migration[8.0]
  # Mirrors Python Alembic 0016 (shared DB, dual migration history).
  # Nullable: legacy/scheduler rows stay NULL = system rows visible to all.
  # No FK: users table is Rails-owned but Python writes these rows.
  #
  # Idempotent: Alembic 0016 may already have added these columns/indexes
  # (shared DB). `db:migrate` re-runs would otherwise abort with
  # PG::DuplicateColumn (this exact failure).
  def change
    add_column :analyses, :user_id, :bigint unless column_exists?(:analyses, :user_id)
    add_index :analyses, :user_id unless index_exists?(:analyses, :user_id)
    add_column :backtest_runs, :user_id, :bigint unless column_exists?(:backtest_runs, :user_id)
    add_index :backtest_runs, :user_id unless index_exists?(:backtest_runs, :user_id)
  end
end

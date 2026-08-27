# frozen_string_literal: true

class AddDeviseToUsers < ActiveRecord::Migration[8.0]
  def up
    # The `users` table was created with a `password_hash` column (matching the
    # original Python/FastAPI schema). Devise's database_authenticatable uses
    # `encrypted_password`. Since the table is empty, rename the column.
    rename_column :users, :password_hash, :encrypted_password

    change_table :users do |t|
      ## Recoverable
      t.string   :reset_password_token
      t.datetime :reset_password_sent_at

      ## Rememberable
      t.datetime :remember_created_at
    end

    add_index :users, :reset_password_token, unique: true
  end

  def down
    remove_index :users, :reset_password_token
    remove_column :users, :reset_password_sent_at
    remove_column :users, :remember_created_at
    remove_column :users, :reset_password_token
    rename_column :users, :encrypted_password, :password_hash
  end
end
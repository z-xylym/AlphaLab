-- AlphaLab schema v1. Backend-only database role. No anonymous browser policies.

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE users (
	id UUID NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	password_hash TEXT NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	daily_calls INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (phone)
);

CREATE TABLE login_attempts (
	key VARCHAR(64) NOT NULL, 
	failures INTEGER NOT NULL, 
	window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE public_cache (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE stock_master (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE stock_prices (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE industries (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE industry_members (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE policies (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE policy_industries (
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	source TEXT NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE auth_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id UUID NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_sessions_expiry ON auth_sessions (expires_at);

CREATE TABLE invitations (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (code_hash)
);

CREATE TABLE api_usage_logs (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	request_key VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	reserved_cost NUMERIC(16, 8) NOT NULL, 
	cost NUMERIC(16, 8) NOT NULL, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	model VARCHAR(100) NOT NULL, 
	response TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, request_key), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_usage_owner_date ON api_usage_logs (user_id, created_at);

CREATE INDEX ix_usage_date ON api_usage_logs (created_at);

CREATE TABLE user_preferences (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_preferences_owner_updated ON user_preferences (user_id, updated_at);

CREATE TABLE chat_sessions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_chat_sessions_owner_updated ON chat_sessions (user_id, updated_at);

CREATE TABLE chat_messages (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_chat_messages_owner_updated ON chat_messages (user_id, updated_at);

CREATE TABLE user_memories (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_memories_owner_updated ON user_memories (user_id, updated_at);

CREATE TABLE research_reports (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_research_reports_owner_updated ON research_reports (user_id, updated_at);

CREATE TABLE watchlists (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_watchlists_owner_updated ON watchlists (user_id, updated_at);

CREATE TABLE watchlist_items (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_watchlist_items_owner_updated ON watchlist_items (user_id, updated_at);

CREATE TABLE portfolios (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_portfolios_owner_updated ON portfolios (user_id, updated_at);

CREATE TABLE portfolio_positions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_portfolio_positions_owner_updated ON portfolio_positions (user_id, updated_at);

CREATE TABLE simulated_trades (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_simulated_trades_owner_updated ON simulated_trades (user_id, updated_at);

CREATE TABLE screening_runs (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_screening_runs_owner_updated ON screening_runs (user_id, updated_at);

CREATE TABLE strategy_results (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_strategy_results_owner_updated ON strategy_results (user_id, updated_at);

ALTER TABLE "users" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "auth_sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "login_attempts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "invitations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "api_usage_logs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public_cache" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "user_preferences" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "chat_sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "chat_messages" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "user_memories" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "research_reports" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "watchlists" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "watchlist_items" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "portfolios" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "portfolio_positions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "simulated_trades" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "screening_runs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "strategy_results" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "stock_master" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "stock_prices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "industries" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "industry_members" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "policies" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "policy_industries" ENABLE ROW LEVEL SECURITY;

INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;

COMMIT;

CREATE TABLE budgets (
	id VARCHAR(100) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	department_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	limit_micros BIGINT NOT NULL, 
	spent_micros BIGINT NOT NULL, 
	reserved_micros BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (limit_micros >= 0), 
	CHECK (spent_micros >= 0), 
	CHECK (reserved_micros >= 0)
);

CREATE TABLE departments (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE events (
	id VARCHAR(64) NOT NULL, 
	type VARCHAR(100) NOT NULL, 
	actor_id VARCHAR(64) NOT NULL, 
	department_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	resource_id VARCHAR(100) NOT NULL, 
	detail JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	delivered_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	roles JSON NOT NULL, 
	team_ids JSON NOT NULL, 
	admin_team_ids JSON NOT NULL, 
	department_ids JSON NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE teams (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	department_id VARCHAR(64) NOT NULL, 
	cost_editor_ids JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
);

CREATE TABLE approvals (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	title VARCHAR(180) NOT NULL, 
	resource_id VARCHAR(64) NOT NULL, 
	department_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64), 
	requester_id VARCHAR(64) NOT NULL, 
	reviewer_id VARCHAR(64), 
	status VARCHAR(20) NOT NULL, 
	payload JSON NOT NULL, 
	reason TEXT NOT NULL, 
	review_note TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id), 
	FOREIGN KEY(requester_id) REFERENCES users (id), 
	FOREIGN KEY(reviewer_id) REFERENCES users (id)
);

CREATE TABLE assets (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	owner_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64), 
	department_id VARCHAR(64) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	endpoint VARCHAR(500) NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	tags JSON NOT NULL, 
	version INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
);

CREATE TABLE api_keys (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	owner_id VARCHAR(64) NOT NULL, 
	asset_id VARCHAR(64) NOT NULL, 
	department_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64), 
	token_hash VARCHAR(64) NOT NULL, 
	encrypted_token TEXT NOT NULL, 
	prefix VARCHAR(20) NOT NULL, 
	models JSON NOT NULL, 
	rpm INTEGER NOT NULL, 
	tpm INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	claimed BOOLEAN NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id), 
	UNIQUE (token_hash)
);

CREATE TABLE reservations (
	id VARCHAR(64) NOT NULL, 
	key_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	budget_ids JSON NOT NULL, 
	amount_micros BIGINT NOT NULL, 
	actual_micros BIGINT, 
	tokens INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	response JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key_id, idempotency_key), 
	FOREIGN KEY(key_id) REFERENCES api_keys (id)
);

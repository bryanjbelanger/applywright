CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    external_id TEXT,
    dedupe_key TEXT UNIQUE NOT NULL,
    
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    remote_status TEXT,
    salary TEXT,
    employment_type TEXT,
    job_url TEXT,
    description TEXT,
    apply_url TEXT,
    
    date_found DATETIME,
    date_applied DATETIME,
    
    application_status TEXT NOT NULL DEFAULT 'discovered',
    source TEXT NOT NULL,
    
    decision TEXT,
    notes TEXT,
    
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_dedupe_key ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_jobs_application_status ON jobs(application_status);
CREATE INDEX IF NOT EXISTS idx_jobs_decision ON jobs(decision);
CREATE INDEX IF NOT EXISTS idx_jobs_source_external ON jobs(source, external_id);
